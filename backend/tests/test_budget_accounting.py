import os

os.environ["DATABASE_URL"] = "sqlite://"

import pytest

from app.budget.accountant import BudgetRejected, reserve_dataset_release
from app.database.connection import Base, SessionLocal, engine
from app.database.models import BudgetLedger, Dataset, PrivacyBudget


def setup_budget():
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        dataset = db.query(Dataset).filter_by(name="budget-test").one_or_none()
        if dataset is None:
            dataset = Dataset(name="budget-test", description="synthetic test dataset")
            db.add(dataset)
            db.flush()
            db.add(PrivacyBudget(dataset_id=dataset.id, scope="dataset", owner_id=None, initial_epsilon=1.0, consumed_epsilon=0))
        return dataset.id


def test_shared_budget_charges_and_blocks_overspend():
    dataset_id = setup_budget()
    with SessionLocal.begin() as db:
        snapshot = reserve_dataset_release(db, dataset_id=dataset_id, epsilon=0.8)
        assert snapshot.consumed_epsilon == pytest.approx(0.8)
        assert snapshot.remaining_epsilon == pytest.approx(0.2)
        assert snapshot.state == "WARNING"
    with SessionLocal.begin() as db:
        with pytest.raises(BudgetRejected):
            reserve_dataset_release(db, dataset_id=dataset_id, epsilon=0.3)
    with SessionLocal() as db:
        assert db.query(BudgetLedger).filter_by(event_type="release").count() == 1


def test_invalid_epsilon_is_rejected_without_charge():
    dataset_id = setup_budget()
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            reserve_dataset_release(db, dataset_id=dataset_id, epsilon=0)
