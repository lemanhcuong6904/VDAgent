"""Read canonical public v1 schemas; this module does not grant host authority."""

import json
from importlib.resources import files


def schema(name: str) -> dict:
    """Return a fresh JSON schema for a supported public wire type.

    This is a reference surface, not a JSON Schema validator. Hosts must validate
    payloads and authorize every operation independently.
    """
    allowed = {
        "agent-manifest", "agent-result", "agent-scope", "artifact-ref", "checkpoint-ref", "evidence-ref",
        "structured-error", "usage-summary", "wait-request", "agent-event", "execution-limits", "port-call", "port-result",
    }
    allowed.add("agent-protocol")
    if name not in allowed:
        raise ValueError("Unsupported public contract schema")
    # File names carry no version; the version lives in each schema's $id (see versions.json).
    resource = files("agent_platform").joinpath("schemas", f"{name}.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))
