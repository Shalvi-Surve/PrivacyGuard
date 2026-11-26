import math


def count_sensitivity() -> float:
    """Add/remove-one-record global sensitivity for COUNT is exactly one."""
    return 1.0


def bounded_sum_sensitivity(lower: float, upper: float, *, adjacency: str = "replace_one") -> float:
    """Global sensitivity for one clipped contribution per record.

    Replace-one adjacency changes one row's contribution from any value in
    [lower, upper] to another, giving U-L. Add/remove-one compares that value
    with the absent row's zero contribution, giving max(|L|, |U|).
    """
    if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
        raise ValueError("finite bounds are required with lower <= upper")
    if adjacency == "replace_one":
        sensitivity = upper - lower
    elif adjacency == "add_remove_one":
        sensitivity = max(abs(lower), abs(upper))
    else:
        raise ValueError("adjacency must be 'add_remove_one' or 'replace_one'")
    if not math.isfinite(sensitivity):
        raise ValueError("sensitivity must be finite")
    return sensitivity


def clip_contributions(values: list[float], lower: float, upper: float) -> list[float]:
    bounded_sum_sensitivity(lower, upper)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("contributions must be finite")
    return [min(upper, max(lower, value)) for value in values]
