from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RiskWeights:
    query_sensitivity: float = 0.20
    data_sensitivity: float = 0.25
    history: float = 0.25
    narrowness: float = 0.20
    query_type: float = 0.10

    def validate(self) -> None:
        values = tuple(self.__dict__.values())
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("risk weights must be finite values in [0, 1]")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-9):
            raise ValueError("risk weights must sum to one")


@dataclass(frozen=True)
class RiskAssessment:
    query_sensitivity: float
    data_sensitivity: float
    history: float
    narrowness: float
    query_type: float
    overall: float


@dataclass(frozen=True)
class AdaptivePolicyConfig:
    epsilon_min: float = 0.1
    epsilon_max: float = 1.0
    risk_penalty: float = 0.6
    cumulative_penalty: float = 0.3
    weights: RiskWeights = RiskWeights()
    policy_id: str = "query-history-adaptive-nominal-v1"

    def validate(self) -> None:
        if not math.isfinite(self.epsilon_min) or not math.isfinite(self.epsilon_max) or not 0 < self.epsilon_min <= self.epsilon_max:
            raise ValueError("epsilon bounds must be finite with 0 < min <= max")
        penalties = (self.risk_penalty, self.cumulative_penalty)
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in penalties):
            raise ValueError("allocation penalties must be finite values in [0, 1]")
        if not self.policy_id:
            raise ValueError("policy_id is required")
        self.weights.validate()


@dataclass(frozen=True)
class EpsilonAllocation:
    nominal_epsilon: float
    unbounded_proposal: float
    risk_score: float
    cumulative_fraction: float
    remaining_epsilon: float
    policy_id: str

    def audit_metadata(self, *, components: RiskAssessment, config: AdaptivePolicyConfig) -> dict:
        return {
            "policy_id": self.policy_id,
            "risk_score": self.risk_score,
            "risk_components": {
                "query_sensitivity": components.query_sensitivity,
                "data_sensitivity": components.data_sensitivity,
                "history_overlap": components.history,
                "predicate_refinement_proxy": components.narrowness,
                "query_type": components.query_type,
            },
            "risk_weights": dict(config.weights.__dict__),
            "cumulative_fraction": self.cumulative_fraction,
            "unbounded_proposal": self.unbounded_proposal,
            "allocated_nominal_epsilon": self.nominal_epsilon,
            "remaining_epsilon_at_decision": self.remaining_epsilon,
            "risk_penalty": config.risk_penalty,
            "cumulative_penalty": config.cumulative_penalty,
            "accounting_status": "nominal_uncertified",
        }


class UnaffordableAllocation(ValueError):
    def __init__(self, decision: EpsilonAllocation):
        super().__init__("The nominal epsilon allocation exceeds the remaining shared dataset budget.")
        self.decision = decision


DEFAULT_POLICY = AdaptivePolicyConfig()

# Experimental M5 policy version. Production query routes retain DEFAULT_POLICY
# until separately validated; these defaults are for newly configured research runs.
EXPERIMENT_POLICY_ID = "query-history-adaptive-nominal-v2"
EXPERIMENT_RISK_PENALTY = 0.1
EXPERIMENT_CUMULATIVE_PENALTY = 0.05


def assess_risk(*, query_sensitivity: float, data_sensitivity: float, history: float,
                narrowness: float, query_type: float, weights: RiskWeights = RiskWeights()) -> RiskAssessment:
    """Compute a bounded policy heuristic; it is not a differential-privacy guarantee."""
    weights.validate()
    components = (query_sensitivity, data_sensitivity, history, narrowness, query_type)
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in components):
        raise ValueError("risk components must be finite values in [0, 1]")
    overall = sum(value * weight for value, weight in zip(components, weights.__dict__.values()))
    return RiskAssessment(*components, overall=overall)


def _validate_allocation_inputs(*, risk: float, cumulative_fraction: float,
                                epsilon_min: float, epsilon_max: float,
                                alpha: float, gamma: float) -> None:
    scores = (risk, cumulative_fraction)
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in scores):
        raise ValueError("risk and cumulative fraction must be finite values in [0, 1]")
    if not math.isfinite(epsilon_min) or not math.isfinite(epsilon_max) or not 0 < epsilon_min <= epsilon_max:
        raise ValueError("epsilon bounds must be finite with 0 < min <= max")
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in (alpha, gamma)):
        raise ValueError("risk and cumulative penalties must be finite values in [0, 1]")


def allocate_epsilon(*, risk: float, cumulative_fraction: float,
                     epsilon_min: float, epsilon_max: float, alpha: float = 0.6,
                     gamma: float = 0.3) -> float:
    """Allocate nominal epsilon from risk once and cumulative utilization once.

    `epsilon = clip(epsilon_max - alpha * risk - gamma * cumulative_fraction,
                    epsilon_min, epsilon_max)`.
    This deterministic policy selects a nominal mechanism parameter; it is not
    a formal privacy accountant or guarantee.
    """
    _validate_allocation_inputs(
        risk=risk, cumulative_fraction=cumulative_fraction,
        epsilon_min=epsilon_min, epsilon_max=epsilon_max, alpha=alpha, gamma=gamma,
    )
    proposal = epsilon_max - alpha * risk - gamma * cumulative_fraction
    return min(epsilon_max, max(epsilon_min, proposal))


def allocate_epsilon_decision(*, assessment: RiskAssessment, cumulative_fraction: float,
                              remaining_epsilon: float, config: AdaptivePolicyConfig = DEFAULT_POLICY) -> EpsilonAllocation:
    """Select and explain nominal epsilon; affordability is checked separately.

    Separating selection from affordability permits an exact cache hit to be
    reused at zero cost even when the remaining budget cannot fund a new draw.
    """
    config.validate()
    checked = assess_risk(
        query_sensitivity=assessment.query_sensitivity,
        data_sensitivity=assessment.data_sensitivity,
        history=assessment.history,
        narrowness=assessment.narrowness,
        query_type=assessment.query_type,
        weights=config.weights,
    )
    if not math.isclose(checked.overall, assessment.overall, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("risk assessment does not match the configured weights")
    if not math.isfinite(remaining_epsilon) or remaining_epsilon < 0:
        raise ValueError("remaining epsilon must be finite and non-negative")
    nominal = allocate_epsilon(
        risk=checked.overall,
        cumulative_fraction=cumulative_fraction,
        epsilon_min=config.epsilon_min,
        epsilon_max=config.epsilon_max,
        alpha=config.risk_penalty,
        gamma=config.cumulative_penalty,
    )
    raw_proposal = config.epsilon_max - config.risk_penalty * checked.overall - config.cumulative_penalty * cumulative_fraction
    decision = EpsilonAllocation(
        nominal_epsilon=nominal,
        unbounded_proposal=raw_proposal,
        risk_score=checked.overall,
        cumulative_fraction=cumulative_fraction,
        remaining_epsilon=remaining_epsilon,
        policy_id=config.policy_id,
    )
    return decision


def require_affordable_allocation(decision: EpsilonAllocation) -> None:
    """Reject, without clamping, when a new release cannot fit the budget."""
    if decision.nominal_epsilon > decision.remaining_epsilon:
        raise UnaffordableAllocation(decision)
