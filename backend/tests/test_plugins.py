"""Plugin loading (plugins spec §5.1): spec order, per-plugin transactions, skipping, shutdown."""

from __future__ import annotations

import logging
import sys
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from vdagent_backend.config import PluginSpec
from vdagent_backend.plugins import PluginManager

MakePlugin = Callable[[str, str], None]

AGENT = """
from vdagent_sdk import PluginConfigError

class Agent:
    def __init__(self, tag):
        self.tag = tag
    async def invoke(self, ctx):
        await ctx.emit_assistant(self.tag)
    async def compact(self, previous_summary, messages):
        return previous_summary
"""


@pytest.fixture
def make_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[MakePlugin]:
    """Write `<name>.py` (with the `Agent` stub prepended) into an importable directory."""
    monkeypatch.syspath_prepend(str(tmp_path))
    names: list[str] = []

    def make(name: str, body: str) -> None:
        (tmp_path / f"{name}.py").write_text(AGENT + textwrap.dedent(body))
        names.append(name)

    yield make
    for name in names:
        sys.modules.pop(name, None)


def _specs(*modules: str) -> list[PluginSpec]:
    return [PluginSpec(m) for m in modules]


async def test_plugins_load_in_order_with_sync_or_async_setup_and_a_copy_of_opts(make_plugin: MakePlugin) -> None:
    make_plugin(
        "p_sync",
        """
        SEEN = []
        def setup(api, opts):
            SEEN.append((api.plugin, dict(opts)))
            opts["mutated"] = True
            api.register_agent(name="b", description="B agent", agent=Agent("b"))
        """,
    )
    make_plugin(
        "p_async",
        """
        async def setup(api, opts):
            api.register_agent(name="a", description="A agent", agent=Agent("a"))
            api.register_agent(name="c", description="C agent", agent=Agent("c"))
        """,
    )
    opts = {"model": "m"}
    manager = PluginManager()
    registry = await manager.load([PluginSpec("p_sync", opts=opts), PluginSpec("p_async")])

    assert registry.names() == ["b", "a", "c"]
    entry = registry.get("a")
    assert entry is not None and (entry.name, entry.description, entry.plugin) == ("a", "A agent", "p_async")
    assert entry.agent.tag == "a"  # type: ignore[attr-defined]
    assert "a" in registry and "zzz" not in registry and registry.get("zzz") is None
    assert sys.modules["p_sync"].SEEN == [("p_sync", {"model": "m"})]
    assert opts == {"model": "m"}  # the spec's opts were not handed out by reference


async def test_a_failing_setup_registers_nothing_and_later_plugins_still_load(
    make_plugin: MakePlugin, caplog: pytest.LogCaptureFixture
) -> None:
    make_plugin(
        "p_half",
        """
        def setup(api, opts):
            api.register_agent(name="half", description="registered before the crash", agent=Agent("h"))
            raise RuntimeError("boom")
        """,
    )
    make_plugin("p_ok", 'def setup(api, opts):\n    api.register_agent(name="ok", description="fine", agent=Agent("ok"))\n')
    caplog.set_level(logging.INFO)

    registry = await PluginManager().load(_specs("p_half", "p_ok"))

    assert registry.names() == ["ok"]
    failed = [r for r in caplog.records if "plugin p_half failed" in r.getMessage()]
    assert len(failed) == 1 and failed[0].levelno == logging.ERROR
    assert "RuntimeError: boom" in failed[0].getMessage() and failed[0].exc_info is not None
    assert any("plugin p_ok loaded: ok" in r.getMessage() for r in caplog.records)


async def test_plugin_config_error_is_logged_without_a_traceback(
    make_plugin: MakePlugin, caplog: pytest.LogCaptureFixture
) -> None:
    make_plugin("p_cfg", 'def setup(api, opts):\n    raise PluginConfigError("missing required environment variable LLM_MODEL")\n')
    registry = await PluginManager().load(_specs("p_cfg"))
    assert registry.names() == []
    (record,) = [r for r in caplog.records if "plugin p_cfg failed" in r.getMessage()]
    assert "missing required environment variable LLM_MODEL" in record.getMessage()
    assert record.exc_info is None


async def test_unimportable_module_and_missing_setup_are_skipped(
    make_plugin: MakePlugin, caplog: pytest.LogCaptureFixture
) -> None:
    make_plugin("p_nosetup", "X = 1\n")
    make_plugin("p_ok2", 'def setup(api, opts):\n    api.register_agent(name="ok", description="fine", agent=Agent("ok"))\n')

    registry = await PluginManager().load(_specs("p_does_not_exist", "p_nosetup", "p_ok2"))

    assert registry.names() == ["ok"]
    messages = [r.getMessage() for r in caplog.records]
    assert any("plugin p_does_not_exist failed: ModuleNotFoundError" in m for m in messages)
    assert any("plugin p_nosetup failed" in m and "setup" in m for m in messages)


async def test_a_name_taken_by_an_earlier_plugin_skips_the_whole_later_plugin(make_plugin: MakePlugin) -> None:
    make_plugin("p_first", 'def setup(api, opts):\n    api.register_agent(name="data", description="first", agent=Agent("1"))\n')
    make_plugin(
        "p_second",
        """
        def setup(api, opts):
            api.register_agent(name="extra", description="would be fine alone", agent=Agent("x"))
            api.register_agent(name="data", description="second", agent=Agent("2"))
        """,
    )
    registry = await PluginManager().load(_specs("p_first", "p_second"))
    assert registry.names() == ["data"]
    entry = registry.get("data")
    assert entry is not None and entry.plugin == "p_first"


@pytest.mark.parametrize(
    ("call", "error"),
    [
        ('api.register_agent(name="", description="d", agent=Agent("x"))', "name"),
        ('api.register_agent(name="n", description="", agent=Agent("x"))', "description"),
        (
            'api.register_agent(name="n", description="d", agent=Agent("x"))\n'
            '        api.register_agent(name="n", description="d", agent=Agent("y"))',
            "already registered",
        ),
    ],
    ids=["empty-name", "empty-description", "duplicate-in-plugin"],
)
async def test_register_agent_rejects_bad_registrations_at_the_call(
    make_plugin: MakePlugin, call: str, error: str
) -> None:
    make_plugin(
        "p_bad",
        f"""
CAUGHT = []
def setup(api, opts):
    try:
        {call.strip()}
    except ValueError as e:
        CAUGHT.append(str(e))
        raise
""",
    )
    registry = await PluginManager().load(_specs("p_bad"))
    assert registry.names() == []
    (message,) = sys.modules["p_bad"].CAUGHT
    assert error in message


async def test_disabled_plugins_are_not_imported(make_plugin: MakePlugin) -> None:
    make_plugin("p_off", 'raise RuntimeError("imported")\n')
    registry = await PluginManager().load([PluginSpec("p_off", enabled=False)])
    assert registry.names() == [] and "p_off" not in sys.modules


async def test_the_api_is_closed_after_loading(make_plugin: MakePlugin) -> None:
    make_plugin("p_keep", "API = []\ndef setup(api, opts):\n    API.append(api)\n")
    await PluginManager().load(_specs("p_keep"))
    (api,) = sys.modules["p_keep"].API
    with pytest.raises(RuntimeError, match="setup"):
        api.register_agent(name="late", description="d", agent=object())
    with pytest.raises(RuntimeError, match="setup"):
        api.on_shutdown(lambda: None)


async def test_shutdown_hooks_run_in_reverse_order_and_survive_failures(
    make_plugin: MakePlugin, caplog: pytest.LogCaptureFixture
) -> None:
    make_plugin(
        "p_hooks",
        """
        import asyncio
        LOG = []
        def hook(tag, fail=None):
            async def run():
                if fail == "raise":
                    raise RuntimeError(f"{tag} broke")
                if fail == "hang":
                    await asyncio.Event().wait()
                LOG.append(tag)
            return run
        def setup(api, opts):
            api.on_shutdown(hook(opts["tag"] + "1"))
            api.on_shutdown(hook(opts["tag"] + "2", opts.get("fail")))
        """,
    )
    make_plugin(
        "p_hooks_b",
        "import p_hooks\ndef setup(api, opts):\n    api.on_shutdown(p_hooks.hook('b1'))\n",
    )
    make_plugin(
        "p_hooks_failed",
        "import p_hooks\ndef setup(api, opts):\n    api.on_shutdown(p_hooks.hook('never'))\n    raise RuntimeError('x')\n",
    )
    manager = PluginManager(shutdown_timeout_s=0.1)
    await manager.load(
        [
            PluginSpec("p_hooks", opts={"tag": "a", "fail": "raise"}),
            PluginSpec("p_hooks_b"),
            PluginSpec("p_hooks_failed"),
        ]
    )
    await manager.close()
    assert sys.modules["p_hooks"].LOG == ["b1", "a1"]  # a2 raised; the failed plugin's hook never ran
    assert any("a2 broke" in r.getMessage() or (r.exc_info and "a2 broke" in str(r.exc_info[1])) for r in caplog.records)

    sys.modules["p_hooks"].LOG.clear()
    manager = PluginManager(shutdown_timeout_s=0.1)
    await manager.load([PluginSpec("p_hooks", opts={"tag": "h", "fail": "hang"})])
    await manager.close()
    assert sys.modules["p_hooks"].LOG == ["h1"]  # the hanging hook timed out, the next still ran
