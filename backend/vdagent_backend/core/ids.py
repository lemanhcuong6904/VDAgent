"""Entity ids: `<prefix>_<12 hex>` (`u_…`, `t_…`, `inv_…`, `ds_…`, `ch_…`, `rp_…`)."""

import secrets


def new_id(prefix: str) -> str:
    """A new random id with the given prefix, e.g. `new_id("t") == "t_3f9a0c1b2d4e"`."""
    return f"{prefix}_{secrets.token_hex(6)}"
