"""Which PostgreSQL warehouse the Backend reads: `VDAGENT_WAREHOUSE_MODE` = aws | local | auto (unset: local).

- `aws`: `VDAGENT_RE_WAREHOUSE_DB` only, the AWS RDS Central Data Warehouse: a remote host, SSL (`require` or stricter,
  `VDAGENT_RE_WAREHOUSE_SSLMODE`), read layer `VDAGENT_RE_WAREHOUSE_SCHEMA` (default `gold`). Never a fallback.
- `local`: the local snapshot, `VDAGENT_RE_WAREHOUSE_LOCAL_DB` or else `VDAGENT_RE_WAREHOUSE_DB`: a local host (e.g.
  host.docker.internal:5433), no SSL required, read layer `re` (`VDAGENT_RE_WAREHOUSE_LOCAL_SCHEMA` / `…_SCHEMA`).
- `auto`: the `aws` target first; the `local` target (`VDAGENT_RE_WAREHOUSE_LOCAL_DB`, required) only when AWS is
  unavailable. `choose` does the probing; `plan` only checks the configuration.

Read layers: `re` is the canonical view schema (docker/warehouse/apply-views.sh); `gold` is the DATA team's own schema,
read through the same canonical views built per session as TEMP views (`re_pg`), so a read-only account works.
Hosts are judged by name: a local host is loopback, private/link-local IP, a single-label name (a Docker service) or a
`.internal` / `.local` name; anything else is remote. No message here carries a user name or password.

May import: `core`.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

MODE_VAR = "VDAGENT_WAREHOUSE_MODE"
DSN_VAR = "VDAGENT_RE_WAREHOUSE_DB"
LOCAL_DSN_VAR = "VDAGENT_RE_WAREHOUSE_LOCAL_DB"
SCHEMA_VAR = "VDAGENT_RE_WAREHOUSE_SCHEMA"
LOCAL_SCHEMA_VAR = "VDAGENT_RE_WAREHOUSE_LOCAL_SCHEMA"
SSLMODE_VAR = "VDAGENT_RE_WAREHOUSE_SSLMODE"

MODES = ("aws", "local", "auto")
SCHEMAS = ("re", "gold")
SECURE_SSLMODES = ("require", "verify-ca", "verify-full")
_PLACEHOLDER_WORDS = ("<", ">", "{", "}", "change_me", "changeme", "change-me", "your_", "your-", "placeholder", "xxxx",
                      "example.com")
_PLACEHOLDER_VALUES = {"user", "username", "password", "pass", "secret", "host", "hostname"}


class WarehouseConfigError(ValueError):
    """The warehouse settings are unusable; the message names the variable to fix, never a credential."""


@dataclass(frozen=True)
class WarehouseTarget:
    """One warehouse to read: where, through which read layer, and with which SSL mode (None: libpq's default)."""

    origin: str  # "aws" | "local"
    dsn: str = field(repr=False)
    schema: str
    sslmode: str | None

    @property
    def host(self) -> str:
        return urlsplit(self.dsn).hostname or ""

    @property
    def port(self) -> int:
        return urlsplit(self.dsn).port or 5432

    @property
    def database(self) -> str:
        return urlsplit(self.dsn).path.lstrip("/")

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}/{self.database}"

    def describe(self) -> str:
        """`origin=… host=… port=… database=… schema=… ssl=…`, safe to log."""
        return (f"origin={self.origin} host={self.host} port={self.port} database={self.database} schema={self.schema} "
                f"ssl={self.sslmode or 'off'}")


@dataclass(frozen=True)
class WarehousePlan:
    mode: str
    primary: WarehouseTarget
    fallback: WarehouseTarget | None = None


def is_local_host(host: str) -> bool:
    """True for loopback, private and link-local addresses, single-label names and `.internal` / `.local` names."""
    name = host.strip("[]").lower()
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return name == "localhost" or "." not in name or name.endswith((".internal", ".local", ".localhost"))
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _value(env: Mapping[str, str], key: str) -> str:
    return (env.get(key) or "").strip()


def _postgres(dsn: str, var: str) -> None:
    if not dsn.startswith(("postgresql://", "postgres://")):
        raise WarehouseConfigError(f"Set {var} in .env to a postgresql://<user>:<password>@<host>:<port>/<database> DSN.")
    url = urlsplit(dsn)
    parts = [url.username or "", url.password or "", url.hostname or ""]
    lowered = [p.lower() for p in parts]
    if not url.hostname or any(w in p for p in lowered for w in _PLACEHOLDER_WORDS) or any(p in _PLACEHOLDER_VALUES for p in lowered[:2]):
        raise WarehouseConfigError(f"{var} still holds placeholder credentials or host; put the real values in .env.")


def _schema(env: Mapping[str, str], var: str, default: str) -> str:
    schema = _value(env, var) or default
    if schema not in SCHEMAS:
        raise WarehouseConfigError(f"{var} must be one of: {', '.join(SCHEMAS)}.")
    return schema


def _aws(env: Mapping[str, str], mode: str) -> WarehouseTarget:
    dsn = _value(env, DSN_VAR)
    _postgres(dsn, DSN_VAR)
    url = urlsplit(dsn)
    if is_local_host(url.hostname or ""):
        raise WarehouseConfigError(
            f"{MODE_VAR}={mode} but {DSN_VAR} points at {url.hostname}, not a remote AWS endpoint. Put the RDS endpoint in "
            f"{DSN_VAR} (and the local snapshot in {LOCAL_DSN_VAR}), or use {MODE_VAR}=local.")
    if not url.password:
        raise WarehouseConfigError(f"{DSN_VAR} has no password; the AWS warehouse needs one (in .env only).")
    in_dsn = (parse_qs(url.query).get("sslmode") or [""])[-1]
    if in_dsn and in_dsn not in SECURE_SSLMODES:
        raise WarehouseConfigError(f"{DSN_VAR} sets sslmode={in_dsn}; the AWS warehouse needs one of: {', '.join(SECURE_SSLMODES)}.")
    sslmode = _value(env, SSLMODE_VAR) or in_dsn or "require"
    if sslmode not in SECURE_SSLMODES:
        raise WarehouseConfigError(f"{SSLMODE_VAR} must be one of: {', '.join(SECURE_SSLMODES)} for the AWS warehouse.")
    return WarehouseTarget("aws", dsn, _schema(env, SCHEMA_VAR, "gold"), sslmode)


def _local(env: Mapping[str, str], mode: str) -> WarehouseTarget:
    local = _value(env, LOCAL_DSN_VAR)
    var, schema_var = (LOCAL_DSN_VAR, LOCAL_SCHEMA_VAR) if local or mode == "auto" else (DSN_VAR, SCHEMA_VAR)
    dsn = local or (_value(env, DSN_VAR) if mode != "auto" else "")
    if mode == "auto" and not dsn:
        raise WarehouseConfigError(f"{MODE_VAR}=auto needs {LOCAL_DSN_VAR}: the local snapshot to fall back to.")
    _postgres(dsn, var)
    host = urlsplit(dsn).hostname or ""
    if not is_local_host(host):
        raise WarehouseConfigError(
            f"{MODE_VAR}={mode} but {var} points at the remote host {host}. Put the local snapshot "
            f"(e.g. host.docker.internal:5433) in {LOCAL_DSN_VAR}, or use {MODE_VAR}=aws.")
    return WarehouseTarget("local", dsn, _schema(env, schema_var, "re"), None)


def plan(env: Mapping[str, str]) -> WarehousePlan:
    """The configured target(s). Raises `WarehouseConfigError` naming the variable to fix."""
    mode = _value(env, MODE_VAR).lower() or "local"
    if mode not in MODES:
        raise WarehouseConfigError(f"{MODE_VAR} must be aws, local or auto.")
    if mode == "aws":
        return WarehousePlan(mode, _aws(env, mode))
    if mode == "local":
        return WarehousePlan(mode, _local(env, mode))
    return WarehousePlan(mode, _aws(env, mode), _local(env, mode))


def choose(p: WarehousePlan, unavailable: Callable[[WarehouseTarget], str | None]) -> tuple[WarehouseTarget, list[str]]:
    """The target to read and what happened. Only `auto` probes (`unavailable` → None, or why AWS cannot be reached)."""
    if p.fallback is None:
        return p.primary, []
    reason = unavailable(p.primary)
    if reason is None:
        return p.primary, ["auto: AWS warehouse available"]
    return p.fallback, [f"auto: AWS warehouse unavailable ({reason}); falling back to the local snapshot"]
