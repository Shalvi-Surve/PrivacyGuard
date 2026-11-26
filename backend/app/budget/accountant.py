from dataclasses import dataclass
import math

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database.models import BudgetLedger, PrivacyBudget

ACCOUNTING_STATUS = "nominal_uncertified"
FORMAL_GUARANTEE_STATUS = "not_formally_established_finite_precision_sampler"


class BudgetRejected(ValueError):
    """The shared dataset budget is missing or cannot cover the release."""


@dataclass(frozen=True)
class BudgetSnapshot:
    initial_epsilon: float
    consumed_epsilon: float
    remaining_epsilon: float
    state: str


def validated_budget_values(initial_epsilon: float, consumed_epsilon: float) -> tuple[float, float]:
    if (not math.isfinite(initial_epsilon) or initial_epsilon <= 0
            or not math.isfinite(consumed_epsilon) or consumed_epsilon < 0
            or consumed_epsilon > initial_epsilon):
        raise ValueError("shared privacy accounting metadata is inconsistent")
    return max(0.0, initial_epsilon - consumed_epsilon), consumed_epsilon / initial_epsilon


def reserve_dataset_release(
    db: Session,
    *,
    dataset_id: int,
    epsilon: float,
    query_id: int | None = None,
    warning_fraction: float = 0.70,
    critical_fraction: float = 0.90,
) -> BudgetSnapshot:
    """Atomically charge a release against the shared dataset budget.

    The caller owns the transaction and must commit only after the protected
    result is ready. If query execution or noise generation fails, roll back.
    The conditional UPDATE is safe under concurrent requests: the database
    checks the balance and acquires the row write lock as one operation.
    """
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon must be finite and positive")
    if not (0 <= warning_fraction < critical_fraction <= 1):
        raise ValueError("thresholds must satisfy 0 <= warning < critical <= 1")
    changed = db.execute(
        update(PrivacyBudget)
        .where(
            PrivacyBudget.dataset_id == dataset_id,
            PrivacyBudget.scope == "dataset",
            PrivacyBudget.owner_id.is_(None),
            PrivacyBudget.consumed_epsilon + epsilon <= PrivacyBudget.initial_epsilon,
        )
        .values(consumed_epsilon=PrivacyBudget.consumed_epsilon + epsilon)
        .execution_options(synchronize_session=False)
        .returning(PrivacyBudget.id)
    )
    budget_id = changed.scalar_one_or_none()
    if budget_id is None:
        exists = db.scalar(select(PrivacyBudget.id).where(
            PrivacyBudget.dataset_id == dataset_id,
            PrivacyBudget.scope == "dataset",
            PrivacyBudget.owner_id.is_(None),
        ))
        if exists is None:
            raise BudgetRejected("No shared dataset privacy budget is configured")
        raise BudgetRejected("The shared dataset privacy budget is exhausted")
    db.add(BudgetLedger(budget_id=budget_id, query_id=query_id, delta_epsilon=epsilon, event_type="release"))
    db.flush()
    budget = db.get(PrivacyBudget, budget_id)
    if budget is None:
        raise BudgetRejected("The shared dataset privacy budget disappeared during reservation")
    db.refresh(budget)
    updated = budget
    remaining = max(0.0, updated.initial_epsilon - updated.consumed_epsilon)
    fraction = updated.consumed_epsilon / updated.initial_epsilon if updated.initial_epsilon > 0 else 1.0
    if fraction >= 1:
        state = "EXHAUSTED"
    elif fraction >= critical_fraction:
        state = "RESTRICTED"
    elif fraction >= warning_fraction:
        state = "WARNING"
    else:
        state = "NORMAL"
    return BudgetSnapshot(updated.initial_epsilon, updated.consumed_epsilon, remaining, state)
