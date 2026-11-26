from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import QueryAnalysisEvent, QueryHistory
from app.query.analysis import QueryAnalysis


HISTORY_WINDOW = 100
SHAPE_REPEAT_SATURATION = 5
PREDICATE_SATURATION = 4


@dataclass(frozen=True)
class QueryHistorySignals:
    overlap: float
    refinement: float
    max_attribute_jaccard: float
    normalized_shape_repeats: float
    normalized_predicate_count: float


def query_history_signals(db: Session, *, dataset_id: int, analysis: QueryAnalysis) -> QueryHistorySignals:
    """Return bounded heuristic signals from safe, dataset-wide query metadata.

    The window spans all authorized users of the shared dataset. It uses only
    stored structural fingerprints and referenced-attribute names; it does not
    read SQL text, predicate literal values, aggregates, or protected outputs.
    """
    protected = db.execute(
        select(QueryHistory.fingerprint, QueryHistory.attributes_accessed)
        .where(QueryHistory.dataset_id == dataset_id, QueryHistory.decision == "released")
        .order_by(QueryHistory.created_at.desc(), QueryHistory.id.desc())
        .limit(HISTORY_WINDOW)
    ).all()
    analyzed = db.execute(
        select(QueryAnalysisEvent.fingerprint, QueryAnalysisEvent.attributes_accessed)
        .where(QueryAnalysisEvent.dataset_id == dataset_id, QueryAnalysisEvent.decision == "analysis_only")
        .order_by(QueryAnalysisEvent.created_at.desc(), QueryAnalysisEvent.id.desc())
        .limit(HISTORY_WINDOW)
    ).all()
    history = list(protected) + list(analyzed)
    shape_repeats = sum(1 for fingerprint, _ in history if fingerprint == analysis.fingerprint)
    current_attributes = {str(value).lower() for value in analysis.columns}
    overlaps = []
    for _, attributes in history:
        prior_attributes = {str(value).lower() for value in (attributes or [])}
        union = current_attributes | prior_attributes
        if union:
            overlaps.append(len(current_attributes & prior_attributes) / len(union))
    max_overlap = max(overlaps, default=0.0)
    normalized_repeats = min(shape_repeats / SHAPE_REPEAT_SATURATION, 1.0)
    normalized_predicates = min(len(analysis.predicates) / PREDICATE_SATURATION, 1.0)
    refinement = 0.5 * normalized_predicates + 0.5 * normalized_repeats
    return QueryHistorySignals(
        overlap=max_overlap,
        refinement=refinement,
        max_attribute_jaccard=max_overlap,
        normalized_shape_repeats=normalized_repeats,
        normalized_predicate_count=normalized_predicates,
    )
