"""S4 static check (build spec 02 §7, DEC-018): lint one SQLite SELECT against the semantic layer, then inject the
snapshot and RBAC filters on every table that needs them. Pure: no database access.

Violations carry a `fix` the T3 generator can act on. Thresholds are never literals: a number compared to a column
that has a config threshold is `HARDCODED_THRESHOLD` (compile `{cfg.<key>}` instead).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from vdagent_contracts.scope import AuthorizedScope
from vdagent_data.semantic.loader import LAYER, Layer

DIALECT = "sqlite"
# column → semantic_config key holding its threshold
THRESHOLD_COLUMNS: dict[str, str] = {"unsold_days_dom": "overdue_threshold_days"}


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str
    fix: str


@dataclass(frozen=True)
class ValidationResult:
    sql: str | None
    violations: tuple[Violation, ...] = ()
    tables: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.violations


def _fail(*violations: Violation) -> ValidationResult:
    return ValidationResult(sql=None, violations=tuple(violations))


def _literal_list(values: list[str]) -> str:
    return "(" + ", ".join("'" + v.replace("'", "''") + "'" for v in values) + ")" if values else "(NULL)"


def _unit_tables(layer: Layer) -> set[str]:
    return {t for t, cols in layer.tables.items() if "unit_key" in cols and t not in layer.rbac}


def _rbac_condition(table: str, alias: str, scope: AuthorizedScope, layer: Layer) -> str | None:
    projects, zones = _literal_list(scope.project_ids), _literal_list(scope.zone_ids)
    if table in layer.rbac:
        column = layer.rbac[table]
        if "zone_key" in layer.tables[table]:
            return f"({alias}.{column} IN {projects} OR {alias}.zone_key IN {zones})"
        return (
            f"({alias}.{column} IN {projects} OR {alias}.{column} IN"
            f" (SELECT project_key FROM dim_zone_master WHERE zone_key IN {zones}))"
        )
    if table in _unit_tables(layer):
        return (
            f"{alias}.unit_key IN (SELECT unit_key FROM dim_unit_master"
            f" WHERE project_key IN {projects} OR zone_key IN {zones})"
        )
    return None


def _lint(stmt: exp.Expression, layer: Layer) -> list[Violation]:
    violations: list[Violation] = []
    ctes = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
    tables = [t for t in stmt.find_all(exp.Table) if t.name not in ctes]
    for table in tables:
        if table.name not in layer.tables:
            violations.append(
                Violation("TABLE_NOT_ALLOWED", f"table {table.name} is not in the semantic layer",
                          "Chỉ dùng các bảng có trong semantic layer.")
            )
    if violations:
        return violations

    aliases = {t.alias_or_name: t.name for t in tables}
    referenced = set(aliases.values())
    output_aliases = {a.alias for a in stmt.find_all(exp.Alias)}
    cte_columns = {c.alias_or_name for cte in stmt.find_all(exp.CTE) for c in cte.this.selects if isinstance(cte.this, exp.Select)}
    for column in stmt.find_all(exp.Column):
        name = column.name
        if column.table:
            table = aliases.get(column.table)
            if table is None:
                continue  # a CTE or subquery alias: its columns were checked where they were defined
            if name not in layer.tables[table]:
                violations.append(Violation("COLUMN_NOT_ALLOWED", f"{table}.{name} is not in the semantic layer",
                                            f"Các cột của {table}: {', '.join(layer.tables[table])}"))
        elif name not in output_aliases and name not in cte_columns and not any(
            name in layer.tables[t] for t in referenced
        ):
            violations.append(Violation("COLUMN_NOT_ALLOWED", f"column {name} is in none of the queried tables",
                                        "Ghi rõ bảng.cột có trong semantic layer."))

    for join in stmt.find_all(exp.Join):
        on = join.args.get("on")
        if on is None:
            continue
        for eq in on.find_all(exp.EQ):
            left, right = eq.this, eq.expression
            if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                continue
            a, b = aliases.get(left.table), aliases.get(right.table)
            if a is None or b is None or a == b:
                continue
            if left.name == right.name == "snapshot_date_key" and {a, b} <= set(layer.snapshot_tables):
                continue  # aligning two snapshot tables on the same load is not a join edge
            if not layer.join_allowed(a, b) or f"{left.name}" not in _edge_columns(layer, a, b):
                fix = layer.join_fix(a, b) or f"JOIN {a} với {b} không có trong đồ thị JOIN; đi qua các cạnh của semantic layer."
                violations.append(Violation("JOIN_NOT_ALLOWED", f"{a}.{left.name} = {b}.{right.name}", fix))

    for cmp in stmt.find_all(exp.GT, exp.GTE, exp.LT, exp.LTE, exp.EQ, exp.NEQ):
        sides = (cmp.this, cmp.expression)
        for column, other in (sides, sides[::-1]):
            if isinstance(column, exp.Column) and column.name in THRESHOLD_COLUMNS and isinstance(other, exp.Literal) and not other.is_string:
                key = THRESHOLD_COLUMNS[column.name]
                violations.append(Violation("HARDCODED_THRESHOLD", f"{column.sql()} compared to literal {other.sql()}",
                                            f"Dùng ngưỡng cấu hình {{cfg.{key}}} thay cho số gõ cứng."))
    return violations


def _edge_columns(layer: Layer, a: str, b: str) -> set[str]:
    columns: set[str] = set()
    for left, right in layer.joins:
        lt, lc = left.split(".")
        rt, rc = right.split(".")
        if {lt, rt} == {a, b}:
            columns |= {lc, rc}
    return columns


def _inject(stmt: exp.Expression, layer: Layer, snapshot_key: int, scope: AuthorizedScope, *, rbac: bool = True) -> None:
    ctes = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
    for table in list(stmt.find_all(exp.Table)):
        if table.name in ctes or table.name not in layer.tables:
            continue
        alias = table.alias_or_name
        conditions: list[str] = []
        if table.name in layer.snapshot_tables:
            conditions.append(f"{alias}.snapshot_date_key = {int(snapshot_key)}")
        condition_rbac = _rbac_condition(table.name, alias, scope, layer) if rbac else None
        if condition_rbac:
            conditions.append(condition_rbac)
        if not conditions:
            continue
        condition = sqlglot.condition(" AND ".join(conditions), dialect=DIALECT)
        parent = table.parent
        if isinstance(parent, exp.Join) and parent.args.get("side"):
            parent.set("on", exp.and_(parent.args["on"], condition) if parent.args.get("on") else condition)
            continue
        select = table.find_ancestor(exp.Select)
        if select is not None:
            select.where(condition, copy=False)


def _is_keys_only(stmt: exp.Expression) -> bool:
    """`SELECT <alias>.unit_key FROM …`: one key column, nothing else."""
    if not isinstance(stmt, exp.Select) or len(stmt.selects) != 1:
        return False
    only = stmt.selects[0]
    return isinstance(only, exp.Column) and only.name == "unit_key"


def validate(
    sql: str, *, snapshot_key: int, scope: AuthorizedScope, layer: Layer = LAYER, keys_only: bool = False
) -> ValidationResult:
    """`keys_only=True` (permissionFilteredCount) accepts only `SELECT x.unit_key FROM …` and injects the snapshot
    filter but not RBAC: the Backend still returns only in-scope keys and reports `hidden_rows` as a number (DEC-039)."""
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except ParseError as exc:
        return _fail(Violation("PARSE_ERROR", str(exc).splitlines()[0], "Viết lại thành một câu SELECT SQLite hợp lệ."))
    if len(statements) != 1:
        return _fail(Violation("MULTI_STATEMENT", f"{len(statements)} statements", "Chỉ gửi đúng một câu SELECT."))
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union)) or any(
        isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create)) for node in stmt.walk()
    ):
        return _fail(Violation("NOT_SELECT", type(stmt).__name__, "Chỉ dùng SELECT hoặc WITH … SELECT (chỉ đọc)."))
    if keys_only and not _is_keys_only(stmt):
        return _fail(Violation("NOT_SELECT", "keys_only needs SELECT <alias>.unit_key", "Chỉ dùng cho câu lấy khoá."))
    violations = _lint(stmt, layer)
    if violations:
        return _fail(*violations)
    tables = tuple(sorted({t.name for t in stmt.find_all(exp.Table) if t.name in layer.tables}))
    _inject(stmt, layer, snapshot_key, scope, rbac=not keys_only)
    return ValidationResult(sql=stmt.sql(dialect=DIALECT), tables=tables)
