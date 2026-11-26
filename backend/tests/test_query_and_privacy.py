import math
import random

import pytest

from app.query.analysis import QueryRejected, analyze_query
from app.privacy.laplace import _noise_from_uniform, _open_interval_uniform, apply_laplace, apply_laplace_for_synthetic_experiment, laplace_noise, laplace_noise_for_synthetic_experiment
from app.privacy.sensitivity import bounded_sum_sensitivity, clip_contributions, count_sensitivity


def test_fingerprint_ignores_case_and_literal_value():
    first = analyze_query("SELECT COUNT(*) FROM employees WHERE department = 'HR'", allowed_tables={"employees"}, allowed_columns={"department"})
    second = analyze_query("select count(*) from EMPLOYEES where DEPARTMENT = 'Finance'", allowed_tables={"employees"}, allowed_columns={"department"})
    assert first.fingerprint == second.fingerprint
    assert first.predicates[0][2] == "HR"


@pytest.mark.parametrize("sql", [
    "DELETE FROM employees",
    "SELECT AVG(salary) FROM employees",
    "SELECT COUNT(*) FROM employees; SELECT COUNT(*) FROM employees",
    "SELECT COUNT(*) FROM secret_table",
    "SELECT COUNT(*) FROM employees WHERE secret = 'x'",
    "SELECT COUNT(*) FROM employees JOIN departments ON employees.department_id = departments.id",
])
def test_unsafe_or_unsupported_query_rejected(sql):
    with pytest.raises(QueryRejected):
        analyze_query(sql, allowed_tables={"employees"}, allowed_columns={"department", "salary"})


def test_dp_sensitivity_and_seeded_noise():
    assert count_sensitivity() == 1
    assert bounded_sum_sensitivity(-100, 500) == 600
    assert bounded_sum_sensitivity(1, 5, adjacency="add_remove_one") == 5
    assert bounded_sum_sensitivity(1, 5, adjacency="replace_one") == 4
    assert clip_contributions([-200, 25, 700], 0, 100) == [0, 25, 100]
    sampled = laplace_noise_for_synthetic_experiment(1, 0.5, seed=7)
    assert sampled == laplace_noise_for_synthetic_experiment(1, 0.5, seed=7)
    u = random.Random(7).getrandbits(53) / 2**53 - 0.5
    expected = -2 * (1 if u >= 0 else -1) * math.log1p(-2 * abs(u))
    assert sampled == expected
    assert apply_laplace_for_synthetic_experiment(2, 0, 1, seed=2) == 2
    with pytest.raises(ValueError):
        laplace_noise_for_synthetic_experiment(1, 0, seed=1)
    with pytest.raises(ValueError):
        bounded_sum_sensitivity(1, 0)


@pytest.mark.parametrize(("lower", "upper", "adjacency", "expected"), [
    (0, 300_000, "add_remove_one", 300_000),
    (1, 5, "add_remove_one", 5),
    (1, 5, "replace_one", 4),
    (-5, 4, "add_remove_one", 5),
    (-5, 4, "replace_one", 9),
    (-5, -2, "add_remove_one", 5),
    (-5, -2, "replace_one", 3),
    (3, 3, "add_remove_one", 3),
    (3, 3, "replace_one", 0),
])
def test_bounded_sum_sensitivity_matches_adjacency(lower, upper, adjacency, expected):
    assert bounded_sum_sensitivity(lower, upper, adjacency=adjacency) == expected


@pytest.mark.parametrize(("lower", "upper"), [(float("nan"), 1), (0, float("inf")), (2, 1), (-1e308, 1e308)])
def test_bounded_sum_rejects_invalid_or_unrepresentable_bounds(lower, upper):
    with pytest.raises(ValueError):
        bounded_sum_sensitivity(lower, upper, adjacency="replace_one")


def test_clipping_preserves_boundary_values_and_rejects_nonfinite_inputs():
    assert clip_contributions([-1, 0, 2.5, 5, 8], 0, 5) == [0, 0, 2.5, 5, 5]
    with pytest.raises(ValueError):
        clip_contributions([float("nan")], 0, 5)


def test_laplace_uses_sensitivity_over_epsilon_and_rejects_overflow(monkeypatch):
    monkeypatch.setattr("app.privacy.laplace.secrets.randbelow", lambda _: 3 * 2**51)
    assert laplace_noise(10, 0.5) == pytest.approx(20 * math.log(2))
    with pytest.raises(ValueError, match="scale must be finite"):
        laplace_noise(1e308, 1e-308)
    with pytest.raises(ValueError, match="noisy aggregate must be finite"):
        apply_laplace(1.7e308, 1e308, 1)


@pytest.mark.parametrize("random_bits", [0, 2**53 - 1])
def test_secure_laplace_randomness_avoids_inverse_cdf_endpoints(monkeypatch, random_bits):
    monkeypatch.setattr("app.privacy.laplace.secrets.randbelow", lambda _: random_bits)
    value = laplace_noise(300_000, 0.1)
    assert math.isfinite(value)
    assert math.isfinite(apply_laplace_for_synthetic_experiment(0, 1, 0.1, seed=7))


@pytest.mark.parametrize("bits", [1, 17, 2**40, 2**52 - 1])
def test_uniform_mapping_is_symmetric_except_the_clamped_zero_word(bits):
    limit = 2**53
    left = _open_interval_uniform(bits)
    right = _open_interval_uniform(limit - bits)
    assert left == -right


def test_endpoint_words_expose_asymmetric_bounded_noise_support(monkeypatch):
    limit = 2**53
    outputs = []
    for bits in (0, limit - 1):
        monkeypatch.setattr("app.privacy.laplace.secrets.randbelow", lambda upper, bits=bits: bits)
        outputs.append(laplace_noise(1.0, 1.0))
    assert outputs[0] == pytest.approx(-53 * math.log(2))
    assert outputs[1] == pytest.approx(52 * math.log(2))
    assert abs(outputs[0]) > outputs[1]
    # randbelow is uniform over 2**53 words, so either endpoint word has
    # probability 2**-53 before any possible output-rounding collisions.


def test_production_sampler_uses_secrets_and_test_sampler_is_separately_seeded(monkeypatch):
    calls = []
    monkeypatch.setattr("app.privacy.laplace.secrets.randbelow", lambda upper: calls.append(upper) or (3 * 2**51))
    production = laplace_noise(1.0, 1.0)
    assert calls == [2**53]

    def forbidden_random_source(*args, **kwargs):
        raise AssertionError("test-only sampling must not draw from production secrets")

    monkeypatch.setattr("app.privacy.laplace.secrets.randbelow", forbidden_random_source)
    seeded_a = laplace_noise_for_synthetic_experiment(1.0, 1.0, seed=19)
    seeded_b = laplace_noise_for_synthetic_experiment(1.0, 1.0, seed=19)
    assert seeded_a == seeded_b
    assert production == pytest.approx(math.log(2))


def test_seeded_laplace_samples_have_empirical_symmetry_mean_and_variance():
    # Deterministic empirical check only; it is not a DP proof.
    values = [laplace_noise_for_synthetic_experiment(1.0, 1.0, seed=seed) for seed in range(20_000)]
    mean = math.fsum(values) / len(values)
    variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
    positive_fraction = sum(value > 0 for value in values) / len(values)
    assert abs(mean) < 0.06
    assert variance == pytest.approx(2.0, abs=0.15)
    assert positive_fraction == pytest.approx(0.5, abs=0.03)


@pytest.mark.parametrize(("sensitivity", "epsilon"), [
    (float("nan"), 1), (float("inf"), 1), (-1, 1),
    (1, float("nan")), (1, float("inf")), (1, 0), (1, -1),
])
def test_laplace_rejects_nonfinite_or_nonpositive_parameters(sensitivity, epsilon):
    with pytest.raises(ValueError):
        laplace_noise(sensitivity, epsilon)


def test_extreme_scale_overflow_and_underflow_are_characterized(monkeypatch):
    with pytest.raises(ValueError, match="scale must be finite"):
        _noise_from_uniform(1e308, 1e-308, 0.25)
    # In the current generic helper, a positive subnormal sensitivity divided
    # by epsilon=2 underflows to a zero scale and silently produces zero noise.
    # This parameter pair is outside PrivacyGuard's configured query range.
    monkeypatch.setattr("app.privacy.laplace.secrets.randbelow", lambda _: 2**52 + 1)
    assert laplace_noise(5e-324, 2.0) == 0.0
    assert _noise_from_uniform(1.0, 1e308, 2**-53) == 0.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_laplace_application_rejects_nonfinite_aggregate_values(value):
    with pytest.raises(ValueError, match="aggregate value must be finite"):
        apply_laplace(value, 1.0, 1.0)
