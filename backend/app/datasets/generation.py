from collections.abc import Iterator
import random


DEPARTMENTS = ("Engineering", "Finance", "HR", "Operations", "Sales", "Legal", "Research", "Support")
DESIGNATIONS = ("Associate", "Specialist", "Senior", "Lead", "Manager")
LOCATIONS = ("North", "South", "East", "West", "Central")
GENDERS = ("Woman", "Man", "Non-binary", "Prefer not to say")
SUPPORTED_EMPLOYEE_SIZES = (5_000, 25_000, 100_000, 500_000)


def iter_employee_rows(dataset_id: int, size: int, seed: int) -> Iterator[dict[str, object]]:
    """Yield fully synthetic, reproducible employee records in bounded memory."""
    if size not in SUPPORTED_EMPLOYEE_SIZES:
        raise ValueError("Choose one of the supported sizes: 5000, 25000, 100000, or 500000")
    rng = random.Random(seed)
    salary_bases = {"Associate": 48_000, "Specialist": 68_000, "Senior": 92_000, "Lead": 120_000, "Manager": 142_000}
    for index in range(size):
        department = DEPARTMENTS[rng.randrange(len(DEPARTMENTS))]
        designation_index = min(4, max(0, int(rng.gauss(2.1, 1.05))))
        designation = DESIGNATIONS[designation_index]
        age = min(65, max(21, int(rng.gauss(39, 9))))
        performance = min(5.0, max(1.0, rng.gauss(2.8 + designation_index * 0.22, 0.65)))
        salary = int(max(32_000, min(260_000, salary_bases[designation] + (age - 38) * 520 + (performance - 3) * 4_000 + rng.gauss(0, 8_500))))
        yield {
            "dataset_id": dataset_id,
            "employee_id": f"D{dataset_id}-{index + 1:07d}",
            "department": department,
            "designation": designation,
            "age": age,
            "gender": GENDERS[rng.randrange(len(GENDERS))],
            "salary": salary,
            "performance_score": round(performance, 2),
            "location": LOCATIONS[rng.randrange(len(LOCATIONS))],
        }
