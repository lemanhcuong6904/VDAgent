"""Plugin loading: import the `config.yaml` `plugins:` entries in order and build the registry.

Each enabled spec is imported in list order and its `setup(api, opts)` is called (and awaited if it
returns an awaitable). `api` buffers the plugin's registrations; they are committed only when
`setup` returns normally, so a failing plugin registers nothing. Failures are logged and skipped:
the Backend starts with whatever loaded. After loading, every `api` is closed. Every agent a plugin
registers gets the spec's `mcp_tools` as its MCP grants.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence

from vdagent_backend.config import PluginSpec
from vdagent_backend.core import describe
from vdagent_backend.plugins.registry import AgentRegistry, RegisteredAgent
from vdagent_sdk import Agent, PluginConfigError

log = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT_S = 5.0

ShutdownHook = Callable[[], Awaitable[None]]


class _PluginAPI:
    """The `PluginAPI` handed to one plugin's `setup`."""

    def __init__(self, spec: PluginSpec, taken: Callable[[str], bool]) -> None:
        self.plugin = spec.module
        self.log = logging.getLogger(f"vdagent.plugin.{spec.module}")
        self._tools = spec.mcp_tools
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
        self.agents.append(
            RegisteredAgent(name=name, description=description, agent=agent, plugin=self.plugin, tools=self._tools)
        )

    def on_shutdown(self, fn: ShutdownHook) -> None:
        self._check_open("on_shutdown")
        self.hooks.append(fn)

    def close(self) -> None:
        self._closed = True


class PluginManager:
    """Loads plugins once and later runs their shutdown hooks."""

    def __init__(self, *, shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S) -> None:
        self._shutdown_timeout_s = shutdown_timeout_s
        self._hooks: list[tuple[str, ShutdownHook]] = []

    async def load(self, specs: Sequence[PluginSpec]) -> AgentRegistry:
        """Load every enabled spec in order; returns the agents of the plugins that loaded."""
        committed: list[RegisteredAgent] = []
        apis: list[_PluginAPI] = []
        taken = lambda name: any(a.name == name for a in committed)  # noqa: E731
        try:
            for spec in specs:
                if not spec.enabled:
                    log.info("plugin %s disabled", spec.module)
                    continue
                api = _PluginAPI(spec, taken)
                apis.append(api)
                try:
                    await self._setup(spec, api)
                except PluginConfigError as e:
                    log.error("plugin %s failed: %s", spec.module, e)
                    continue
                except Exception as e:
                    log.error("plugin %s failed: %s", spec.module, describe(e), exc_info=e)
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
                log.error("plugin %s: shutdown hook failed: %s", plugin, describe(e), exc_info=e)
