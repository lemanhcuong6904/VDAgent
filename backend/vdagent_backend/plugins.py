"""Agent plugins (plugins spec §5.1): load `config.yaml` `plugins:` like lazy.nvim, keep a registry.

Each enabled spec is imported in list order and its `setup(api, opts)` is called (and awaited if it
returns an awaitable). `api` buffers the plugin's registrations; they are committed only when
`setup` returns normally, so a failing plugin registers nothing. Failures are logged and skipped:
the Backend starts with whatever loaded. After loading, every `api` is closed.

The resulting `AgentRegistry` is immutable and is the only source of agent names, descriptions and
objects for the engine and the API.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass

from vdagent_backend.config import PluginSpec
from vdagent_sdk import Agent, PluginConfigError

log = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT_S = 5.0

ShutdownHook = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class RegisteredAgent:
    name: str
    description: str
    agent: Agent
    plugin: str


class AgentRegistry:
    """Registered agents in registration order. Immutable."""

    def __init__(self, agents: Iterable[RegisteredAgent] = ()) -> None:
        self._agents: dict[str, RegisteredAgent] = {}
        for entry in agents:
            if entry.name in self._agents:
                raise ValueError(f"agent '{entry.name}' is registered twice")
            self._agents[entry.name] = entry

    def names(self) -> list[str]:
        return list(self._agents)

    def get(self, name: str) -> RegisteredAgent | None:
        return self._agents.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._agents

    def __iter__(self) -> Iterator[RegisteredAgent]:
        return iter(self._agents.values())


class _PluginAPI:
    """The `PluginAPI` handed to one plugin's `setup`."""

    def __init__(self, plugin: str, taken: Callable[[str], bool]) -> None:
        self.plugin = plugin
        self.log = logging.getLogger(f"vdagent.plugin.{plugin}")
        self._taken = taken
        self._closed = False
        self.agents: list[RegisteredAgent] = []
        self.hooks: list[ShutdownHook] = []

    def _check_open(self, what: str) -> None:
        if self._closed:
            raise RuntimeError(f"{what}: plugin {self.plugin} can only register while its setup() runs")

    def register_agent(self, *, name: str, description: str, agent: Agent) -> None:
        self._check_open("register_agent")
        if not isinstance(name, str) or not name.strip():  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError("register_agent: name must be a non-empty string")
        if not isinstance(description, str) or not description.strip():  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError(f"register_agent({name!r}): description must be a non-empty string")
        if self._taken(name) or any(a.name == name for a in self.agents):
            raise ValueError(f"register_agent: agent '{name}' is already registered")
        self.agents.append(RegisteredAgent(name=name, description=description, agent=agent, plugin=self.plugin))

    def on_shutdown(self, fn: ShutdownHook) -> None:
        self._check_open("on_shutdown")
        self.hooks.append(fn)

    def close(self) -> None:
        self._closed = True


def _describe(exc: BaseException) -> str:
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class PluginManager:
    def __init__(self, *, shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S) -> None:
        self._shutdown_timeout_s = shutdown_timeout_s
        self._hooks: list[tuple[str, ShutdownHook]] = []

    async def load(self, specs: Sequence[PluginSpec]) -> AgentRegistry:
        committed: list[RegisteredAgent] = []
        apis: list[_PluginAPI] = []
        taken = lambda name: any(a.name == name for a in committed)  # noqa: E731
        try:
            for spec in specs:
                if not spec.enabled:
                    log.info("plugin %s disabled", spec.module)
                    continue
                api = _PluginAPI(spec.module, taken)
                apis.append(api)
                try:
                    await self._setup(spec, api)
                except PluginConfigError as e:
                    log.error("plugin %s failed: %s", spec.module, e)
                    continue
                except Exception as e:
                    log.error("plugin %s failed: %s", spec.module, _describe(e), exc_info=e)
                    continue
                committed.extend(api.agents)
                self._hooks.extend((spec.module, hook) for hook in api.hooks)
                names = ", ".join(a.name for a in api.agents) or "(no agents)"
                log.info("plugin %s loaded: %s", spec.module, names)
        finally:
            for api in apis:
                api.close()
        return AgentRegistry(committed)

    @staticmethod
    async def _setup(spec: PluginSpec, api: _PluginAPI) -> None:
        module = importlib.import_module(spec.module)
        setup = getattr(module, "setup", None)
        if not callable(setup):
            raise TypeError(f"module {spec.module} has no callable setup(api, opts)")
        result = setup(api, dict(spec.opts))
        if inspect.isawaitable(result):
            await result

    async def close(self) -> None:
        """Run shutdown hooks in reverse registration order; a failing or slow hook does not stop the rest."""
        hooks, self._hooks = self._hooks, []
        for plugin, hook in reversed(hooks):
            try:
                await asyncio.wait_for(hook(), self._shutdown_timeout_s)
            except TimeoutError:
                log.error("plugin %s: shutdown hook timed out after %gs", plugin, self._shutdown_timeout_s)
            except Exception as e:
                log.error("plugin %s: shutdown hook failed: %s", plugin, _describe(e), exc_info=e)
