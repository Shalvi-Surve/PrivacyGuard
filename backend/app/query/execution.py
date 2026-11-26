from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.database.models import Dataset, DatasetMetadata, Employee
from app.query.analysis import PredicateNode, QueryAnalysis, QueryRejected
from app.privacy.sensitivity import bounded_sum_sensitivity, count_sensitivity


EMPLOYEE_COLUMNS = {
    "employee_id": Employee.employee_id,
    "department": Employee.department,
    "designation": Employee.designation,
    "age": Employee.age,
    "gender": Employee.gender,
    "salary": Employee.salary,
    "performance_score": Employee.performance_score,
    "location": Employee.location,
}
SUM_BOUNDS = {"salary": (0.0, 300_000.0), "performance_score": (1.0, 5.0)}
ADJACENCY_MODEL = "add_remove_one_record"
PROTECTED_RELEASE_POLICY_VERSION = "protected-release-v3-adaptive-accounting"


def sensitivity_for(analysis: QueryAnalysis) -> tuple[float, float, float | None, float | None]:
    if analysis.query_type == "count":
        return count_sensitivity(), 0.0, None, None
    if analysis.aggregate_column not in SUM_BOUNDS:
        raise QueryRejected("SUM is supported only for columns with configured contribution bounds")
    lower, upper = SUM_BOUNDS[analysis.aggregate_column]
    return bounded_sum_sensitivity(lower, upper, adjacency="add_remove_one"), 0.0, lower, upper


def _compile_predicate(node: PredicateNode | None):
    if node is None:
        return None
    if node.operator:
        parts = [_compile_predicate(child) for child in node.children]
        if any(part is None for part in parts):
            raise QueryRejected("Invalid predicate tree")
        return and_(*parts) if node.operator == "and" else or_(*parts)
    if not node.column or node.column not in EMPLOYEE_COLUMNS or node.comparison not in {"=", "!=", ">", ">=", "<", "<="}:
        raise QueryRejected("Predicate is not supported for this dataset")
    column = EMPLOYEE_COLUMNS[node.column]
    value = node.value
    return {
        "=": lambda: column == value,
        "!=": lambda: column != value,
        ">": lambda: column > value,
        ">=": lambda: column >= value,
        "<": lambda: column < value,
        "<=": lambda: column <= value,
    }[node.comparison]()


def execute_internal_aggregate(db: Session, dataset: Dataset, metadata: DatasetMetadata, analysis: QueryAnalysis) -> float:
    """Compile only validated AST data into SQLAlchemy expressions; never execute input SQL."""
    if metadata.table_name != "employees":
        raise QueryRejected("This executor only supports registered employee datasets")
    if analysis.table != "employees":
        raise QueryRejected("Query table does not match the selected dataset")
    conditions = [Employee.dataset_id == dataset.id]
    predicate = _compile_predicate(analysis.predicate_tree)
    if predicate is not None:
        conditions.append(predicate)

    if analysis.query_type == "count":
        column = func.count() if analysis.aggregate_column is None else func.count(EMPLOYEE_COLUMNS[analysis.aggregate_column])
    elif analysis.query_type == "sum" and analysis.aggregate_column in SUM_BOUNDS:
        source_column = EMPLOYEE_COLUMNS[analysis.aggregate_column]
        lower, upper = SUM_BOUNDS[analysis.aggregate_column]
        bounded_contribution = case((source_column < lower, lower), (source_column > upper, upper), else_=source_column)
        column = func.sum(bounded_contribution)
    else:
        raise QueryRejected("Aggregate is not supported by the selected dataset")

    raw_aggregate = db.scalar(select(column).select_from(Employee).where(*conditions))
    return float(raw_aggregate or 0.0)
