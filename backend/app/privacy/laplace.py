import math
import secrets
import random


def _noise_from_uniform(sensitivity: float, epsilon: float, u: float) -> float:
    if not math.isfinite(sensitivity) or sensitivity < 0:
        raise ValueError("sensitivity must be finite and non-negative")
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon must be finite and positive")
    if sensitivity == 0:
        return 0.0
    scale = sensitivity / epsilon
    if not math.isfinite(scale):
        raise ValueError("Laplace scale must be finite")
    sign = 1.0 if u >= 0 else -1.0
    return -scale * sign * math.log1p(-2 * abs(u))


def _open_interval_uniform(bits: int) -> float:
    """Map 53 random bits to the representable open interval (-0.5, 0.5)."""
    value = bits / 2**53 - 0.5
    return min(math.nextafter(0.5, 0.0), max(math.nextafter(-0.5, 0.0), value))


def laplace_noise(sensitivity: float, epsilon: float) -> float:
    """Sample Lap(0, sensitivity/epsilon) with a cryptographic RNG."""
    # Clamp after conversion: at 53-bit precision a midpoint can round to 0.5.
    u = _open_interval_uniform(secrets.randbelow(2**53))
    return _noise_from_uniform(sensitivity, epsilon, u)


def laplace_noise_for_synthetic_experiment(sensitivity: float, epsilon: float, *, seed: int) -> float:
    """Reproducible sampling for controlled experiments over synthetic data only."""
    u = _open_interval_uniform(random.Random(seed).getrandbits(53))
    return _noise_from_uniform(sensitivity, epsilon, u)


def apply_laplace(value: float, sensitivity: float, epsilon: float) -> float:
    if not math.isfinite(value):
        raise ValueError("aggregate value must be finite")
    result = value + laplace_noise(sensitivity, epsilon)
    if not math.isfinite(result):
        raise ValueError("noisy aggregate must be finite")
    return result


def apply_laplace_for_synthetic_experiment(value: float, sensitivity: float, epsilon: float, *, seed: int) -> float:
    if not math.isfinite(value):
        raise ValueError("aggregate value must be finite")
    result = value + laplace_noise_for_synthetic_experiment(sensitivity, epsilon, seed=seed)
    if not math.isfinite(result):
        raise ValueError("noisy aggregate must be finite")
    return result
