from dataclasses import dataclass
import hashlib
import json
import math

import sqlglot
from sqlglot import exp


@dataclass(frozen=True)
class QueryAnalysis:
    canonical_sql: str
    fingerprint: str
    query_type: str
    table: str
    aggregate: str
    aggregate_column: str | None
    columns: tuple[str, ...]
    predicates: tuple[tuple[str, str, str | int | float | bool], ...]
    predicate_tree: "PredicateNode | None"
    release_key: str


@dataclass(frozen=True)
class PredicateNode:
    operator: str | None = None
    column: str | None = None
    comparison: str | None = None
    value: str | int | float | bool | None = None
    children: tuple["PredicateNode", ...] = ()


class QueryRejected(ValueError):
    """Raised when a query is outside the restricted analytical subset."""


ALLOWED_OPERATORS = {
    exp.EQ: "=", exp.NEQ: "!=", exp.GT: ">", exp.GTE: ">=", exp.LT: "<", exp.LTE: "<=",
}


def _identifier(node: exp.Expression) -> str:
    if not isinstance(node, exp.Column) or node.table or node.db or node.catalog:
        raise QueryRejected("Only unqualified column references are supported")
    return node.name.lower()


def _literal(node: exp.Expression):
    if not isinstance(node, exp.Literal):
        raise QueryRejected("Predicates must compare a column with a literal")
    if node.is_string:
        return node.this
    raw = str(node.this)
    try:
        value = int(raw)
        return value
    except ValueError:
        try:
            value = float(raw)
        except ValueError as exc:
            raise QueryRejected("Unsupported literal") from exc
        if not math.isfinite(value):
            raise QueryRejected("Numeric predicate values must be finite")
        return value


def _predicate_tree(node: exp.Expression | None) -> PredicateNode | None:
    if node is None:
        return None
    if isinstance(node, (exp.And, exp.Or)):
        operator = "and" if isinstance(node, exp.And) else "or"
        return PredicateNode(operator=operator, children=(_predicate_tree(node.this), _predicate_tree(node.expression)))  # type: ignore[arg-type]
    for cls, symbol in ALLOWED_OPERATORS.items():
        if isinstance(node, cls):
            left, right = node.this, node.expression
            if isinstance(left, exp.Literal) and isinstance(right, exp.Column):
                left, right = right, left
                reverse = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "=": "=", "!=": "!="}
                symbol = reverse[symbol]
            return PredicateNode(column=_identifier(left), comparison=symbol, value=_literal(right))
    raise QueryRejected("WHERE supports only AND/OR of column-to-literal comparisons")


def _flatten_predicates(node: PredicateNode | None) -> list[tuple[str, str, str | int | float | bool]]:
    if node is None:
        return []
    if node.operator:
        return [item for child in node.children for item in _flatten_predicates(child)]
    assert node.column is not None and node.comparison is not None
    return [(node.column, node.comparison, node.value)]  # type: ignore[list-item]


def analyze_query(sql: str, *, allowed_tables: set[str], allowed_columns: set[str]) -> QueryAnalysis:
    if not sql or len(sql) > 4000:
        raise QueryRejected("Query is empty or exceeds the 4000 character limit")
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise QueryRejected("SQL could not be parsed as PostgreSQL") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise QueryRejected("Exactly one SELECT statement is supported")
    query = statements[0]
    unsupported_clauses = {key for key, value in query.args.items() if value is not None and key not in {"expressions", "from_", "where"}}
    if unsupported_clauses:
        raise QueryRejected(f"Unsupported SELECT clauses: {', '.join(sorted(unsupported_clauses))}")
    if any(isinstance(node, exp.Subquery) for node in query.walk()):
        raise QueryRejected("Subqueries are not supported")
    tables = list(query.find_all(exp.Table))
    from_clause = query.args.get("from_")
    if len(tables) != 1 or from_clause is None or from_clause.this is not tables[0] or tables[0].db or tables[0].catalog:
        raise QueryRejected("Exactly one unqualified table is supported")
    table = tables[0].name.lower()
    if table not in {name.lower() for name in allowed_tables}:
        raise QueryRejected("Table is not approved")
    projection = query.expressions
    if len(projection) != 1:
        raise QueryRejected("Exactly one aggregate expression is supported")
    expression = projection[0]
    if isinstance(expression, exp.Alias):
        expression = expression.this
    if not isinstance(expression, exp.AggFunc) or not isinstance(expression, (exp.Count, exp.Sum)):
        raise QueryRejected("Only COUNT and SUM aggregates are supported")
    if expression.args.get("distinct"):
        raise QueryRejected("DISTINCT aggregates are not supported")
    if any(expression.args.get(key) is not None for key in ("filter", "order", "limit", "nulls_excluded")):
        raise QueryRejected("Aggregate modifiers are not supported")
    aggregate = "count" if isinstance(expression, exp.Count) else "sum"
    arg = expression.this
    aggregate_column = None
    if aggregate == "count" and isinstance(arg, exp.Star):
        pass
    else:
        aggregate_column = _identifier(arg)
        if aggregate_column not in {column.lower() for column in allowed_columns}:
            raise QueryRejected("Aggregate column is not approved")
    predicate_tree = _predicate_tree(query.args.get("where").this if query.args.get("where") else None)
    predicates = _flatten_predicates(predicate_tree)
    for column, _, _ in predicates:
        if column not in {name.lower() for name in allowed_columns}:
            raise QueryRejected(f"Predicate column '{column}' is not approved")
    columns = tuple(sorted(set(([aggregate_column] if aggregate_column else []) + [p[0] for p in predicates])))

    # Canonical structure replaces literal values with a constant marker.
    normalized = query.copy()
    for literal in list(normalized.find_all(exp.Literal)):
        literal.replace(exp.Literal.string("?"))
    canonical = normalized.sql(dialect="postgres", pretty=False).lower()
    release_key = hashlib.sha256(query.sql(dialect="postgres", pretty=False).encode()).hexdigest()
    structure = {"sql": canonical, "table": table, "predicates": [(c, op) for c, op, _ in predicates]}
    fingerprint = hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).hexdigest()
    return QueryAnalysis(
        canonical_sql=canonical,
        fingerprint=fingerprint,
        query_type=aggregate,
        table=table,
        aggregate=aggregate,
        aggregate_column=aggregate_column,
        columns=columns,
        predicates=tuple(predicates),
        predicate_tree=predicate_tree,
        release_key=release_key,
    )


def _hash_material(material: dict) -> str:
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def protected_release_lookup_key(
    *, analysis: QueryAnalysis, dataset_id: int, dataset_version: int,
    authorization_scope: list[int], policy_version: str, mechanism: str,
    sensitivity: float, clipping_bounds: dict[str, float] | None, adjacency_model: str,
    epsilon: float,
) -> str:
    """Stable idempotency identity for a query release request.

    Query literals are retained through ``analysis.release_key``; the structural
    fingerprint alone is intentionally insufficient because it masks values.
    The key includes dataset version, effective role scope, mechanism and all
    mathematical release parameters, including the adaptive epsilon selected
    for this request. A changed allocation is a distinct release identity.
    """
    material = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "canonical_fingerprint": analysis.fingerprint,
        "normalized_query_with_values": analysis.release_key,
        "authorization_scope": sorted(set(authorization_scope)),
        "policy_version": policy_version,
        "mechanism": mechanism,
        "sensitivity": sensitivity,
        "clipping_bounds": clipping_bounds,
        "adjacency_model": adjacency_model,
        "epsilon": epsilon,
    }
    return _hash_material(material)


def protected_release_key(
    *, lookup_key: str, epsilon: float, sensitivity: float, mechanism: str,
    clipping_bounds: dict[str, float] | None, adjacency_model: str,
    dataset_version: int, policy_version: str,
) -> str:
    """Immutable digest of the exact DP configuration used for the stored draw."""
    return _hash_material({
        "lookup_key": lookup_key,
        "epsilon": epsilon,
        "sensitivity": sensitivity,
        "mechanism": mechanism,
        "clipping_bounds": clipping_bounds,
        "adjacency_model": adjacency_model,
        "dataset_version": dataset_version,
        "policy_version": policy_version,
    })
