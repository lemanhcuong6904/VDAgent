"""Build and import the SDK wheel in temporary directories; never install globally."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

root = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix="team6-python-package-") as temporary:
    work = Path(temporary)
    source = work / "sdk"
    shutil.copytree(root / "sdk/python", source, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "dist"))
    wheels = work / "wheels"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheels), str(source)],
        check=True, timeout=180,
    )
    artifacts = list(wheels.glob("*.whl"))
    if len(artifacts) != 1:
        raise RuntimeError("Expected exactly one SDK wheel")
    wheel = artifacts[0]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if not all(name.startswith(("agent_platform/", "team6_agent_platform-0.1.0.dist-info/")) for name in names):
            raise RuntimeError("Unexpected package contents")
        metadata = archive.read("team6_agent_platform-0.1.0.dist-info/METADATA").decode()
        if "Requires-Dist:" in metadata:
            raise RuntimeError("SDK must remain runtime dependency-free")
    # Import directly from the built wheel, without the source checkout on sys.path.
    env = {**os.environ, "PYTHONPATH": str(wheel)}
    subprocess.run(
        [sys.executable, "-c", "import agent_platform; from agent_platform.contracts import schema; assert agent_platform.AGENT_RUNNER_PROTOCOL == 'agent-runner.v2'; assert schema('agent-scope')['title'] == 'AgentScope'; assert len(schema('port-call')['oneOf']) == 20; assert len(schema('port-result')['oneOf']) == 20; print('Wheel protocol and schema resource import PASS')"],
        cwd=work, env=env, check=True, timeout=30,
    )
    print(json.dumps({"status": "PASS", "wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "files": len(names), "python": sys.version.split()[0]}))
