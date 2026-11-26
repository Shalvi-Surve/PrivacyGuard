import pytest

from app.privacy.policy import (
    AdaptivePolicyConfig, RiskWeights, UnaffordableAllocation, allocate_epsilon,
    allocate_epsilon_decision, assess_risk, require_affordable_allocation,
)


def test_risk_is_bounded_weighted_and_explainable():
    result = assess_risk(query_sensitivity=1, data_sensitivity=0, history=0.5, narrowness=0, query_type=1)
    assert result.overall == pytest.approx(0.425)
    assert result.history == 0.5
    assert 0 <= result.overall <= 1


def test_epsilon_allocation_is_deterministic_and_history_is_in_risk_once():
    risk = assess_risk(query_sensitivity=0, data_sensitivity=0, history=0.5, narrowness=0, query_type=0)
    a = allocate_epsilon_decision(assessment=risk, cumulative_fraction=0, remaining_epsilon=1)
    b = allocate_epsilon_decision(assessment=risk, cumulative_fraction=0, remaining_epsilon=1)
    assert a == b
    assert a.nominal_epsilon == pytest.approx(1 - 0.6 * risk.overall)
    assert a.nominal_epsilon >= 0.1


def test_higher_risk_and_cumulative_spend_reduce_allocation_within_bounds():
    low = allocate_epsilon(risk=0, cumulative_fraction=0, epsilon_min=0.1, epsilon_max=1)
    high = allocate_epsilon(risk=1, cumulative_fraction=1, epsilon_min=0.1, epsilon_max=1)
    assert low == 1
    assert high == pytest.approx(0.1)
    assert 0.1 <= high <= low <= 1


def test_configurable_policy_penalties_control_adaptation_without_exceeding_bounds():
    assessment_low = assess_risk(query_sensitivity=0, data_sensitivity=0, history=0, narrowness=0, query_type=0)
    assessment_high = assess_risk(query_sensitivity=1, data_sensitivity=1, history=1, narrowness=1, query_type=1)
    config = AdaptivePolicyConfig(epsilon_min=.1, epsilon_max=.5, risk_penalty=.2, cumulative_penalty=.1, policy_id="calibration-test")
    low = allocate_epsilon_decision(assessment=assessment_low, cumulative_fraction=0, remaining_epsilon=2, config=config)
    high = allocate_epsilon_decision(assessment=assessment_high, cumulative_fraction=1, remaining_epsilon=2, config=config)
    assert low.nominal_epsilon == pytest.approx(.5)
    assert high.nominal_epsilon == pytest.approx(.2)
    assert high.nominal_epsilon < low.nominal_epsilon
    assert high.policy_id == "calibration-test"


def test_unaffordable_allocation_is_rejected_not_clamped():
    assessment = assess_risk(query_sensitivity=1, data_sensitivity=1, history=1, narrowness=1, query_type=1)
    decision = allocate_epsilon_decision(assessment=assessment, cumulative_fraction=1, remaining_epsilon=0.05)
    assert decision.nominal_epsilon == pytest.approx(0.1)
    with pytest.raises(UnaffordableAllocation):
        require_affordable_allocation(decision)


@pytest.mark.parametrize("config", [
    AdaptivePolicyConfig(epsilon_min=0, epsilon_max=1),
    AdaptivePolicyConfig(epsilon_min=2, epsilon_max=1),
    AdaptivePolicyConfig(risk_penalty=float("nan")),
    AdaptivePolicyConfig(risk_penalty=1.01),
    AdaptivePolicyConfig(cumulative_penalty=-1),
    AdaptivePolicyConfig(weights=RiskWeights(1, 1, 1, 1, 1)),
])
def test_policy_rejects_invalid_configurations(config):
    with pytest.raises(ValueError):
        config.validate()


@pytest.mark.parametrize("kwargs", [
    {"risk": 2, "cumulative_fraction": 0, "epsilon_min": .1, "epsilon_max": 1},
    {"risk": 0, "cumulative_fraction": float("nan"), "epsilon_min": .1, "epsilon_max": 1},
    {"risk": 0, "cumulative_fraction": 0, "epsilon_min": 0, "epsilon_max": 1},
    {"risk": 0, "cumulative_fraction": 0, "epsilon_min": .1, "epsilon_max": 1, "alpha": -1},
    {"risk": 0, "cumulative_fraction": 0, "epsilon_min": .1, "epsilon_max": 1, "alpha": 1.01},
])
def test_policy_rejects_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        allocate_epsilon(**kwargs)


@pytest.mark.parametrize("values", [(-0.1, 0), (float("nan"), 0), (0, float("nan")), (1.1, 0), (0, float("inf"))])
def test_risk_components_must_be_finite_and_normalized(values):
    with pytest.raises(ValueError):
        assess_risk(query_sensitivity=values[0], data_sensitivity=0, history=0, narrowness=0, query_type=values[1])
