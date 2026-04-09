"""Tests for the Labour Scheduling API."""

import pytest
from fastapi.testclient import TestClient

from labour_scheduling.api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_payload(**overrides) -> dict:
    """Return a minimal valid payload, overriding any fields as needed."""
    base = {
        "num_workers": 3,
        "num_days": 2,
        "num_shifts": 2,
        "min_shifts_per_worker": 1,
        "max_shifts_per_worker": 4,
        "demand": [[1, 1], [1, 1]],
    }
    base.update(overrides)
    return base


def full_availability(num_workers: int, num_days: int, num_shifts: int) -> list:
    return [
        [[True] * num_shifts for _ in range(num_days)]
        for _ in range(num_workers)
    ]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Successful solves
# ---------------------------------------------------------------------------

class TestSolveSuccess:
    def test_minimal_case_is_feasible(self):
        payload = make_payload(
            num_workers=1, num_days=1, num_shifts=1,
            min_shifts_per_worker=1, max_shifts_per_worker=1,
            demand=[[1]],
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("OPTIMAL", "FEASIBLE")
        assert len(data["assignments"]) == 1
        assert data["assignments"][0]["worker"] == "Worker 1"

    def test_optimal_status_returned(self):
        """A simple, unconstrained problem should return OPTIMAL."""
        payload = make_payload()
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "OPTIMAL"

    def test_assignments_match_demand(self):
        """Total assignments per (day, shift) must equal the demand value."""
        payload = make_payload(
            num_workers=4,
            num_days=3,
            num_shifts=2,
            min_shifts_per_worker=0,
            max_shifts_per_worker=6,
            demand=[[2, 1], [1, 2], [2, 2]],
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("OPTIMAL", "FEASIBLE")

        # Count assignments per (day, shift)
        counts: dict[tuple[int, int], int] = {}
        for a in data["assignments"]:
            key = (a["day"], a["shift"])
            counts[key] = counts.get(key, 0) + 1

        demand = payload["demand"]
        for d in range(payload["num_days"]):
            for s in range(payload["num_shifts"]):
                expected = demand[d][s]
                actual = counts.get((d + 1, s + 1), 0)
                assert actual == expected, f"day={d+1} shift={s+1}: expected {expected}, got {actual}"

    def test_each_worker_at_most_one_shift_per_day(self):
        """No worker should be assigned more than one shift on the same day."""
        payload = make_payload(
            num_workers=3,
            num_days=3,
            num_shifts=3,
            min_shifts_per_worker=1,
            max_shifts_per_worker=9,
            demand=[[1, 1, 1], [1, 1, 1], [1, 1, 1]],
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("OPTIMAL", "FEASIBLE")

        from collections import defaultdict
        worker_day: dict = defaultdict(set)
        for a in data["assignments"]:
            assert a["shift"] not in worker_day[(a["worker"], a["day"])], (
                f"{a['worker']} assigned twice on day {a['day']}"
            )
            worker_day[(a["worker"], a["day"])].add(a["shift"])

    def test_shifts_per_worker_totals_are_correct(self):
        payload = make_payload()
        response = client.post("/solve", json=payload)
        data = response.json()
        assert data["status"] in ("OPTIMAL", "FEASIBLE")

        # Recount from assignments
        from collections import Counter
        counter = Counter(a["worker"] for a in data["assignments"])
        for worker, count in data["shifts_per_worker"].items():
            assert count == counter.get(worker, 0)

    def test_worker_names_used_in_assignments(self):
        names = ["Alice", "Bob", "Carol"]
        payload = make_payload(worker_names=names)
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("OPTIMAL", "FEASIBLE")
        assigned_workers = {a["worker"] for a in data["assignments"]}
        assert assigned_workers <= set(names)
        assert set(data["shifts_per_worker"].keys()) == set(names)

    def test_default_worker_names_when_omitted(self):
        payload = make_payload()
        response = client.post("/solve", json=payload)
        data = response.json()
        assert set(data["shifts_per_worker"].keys()) == {"Worker 1", "Worker 2", "Worker 3"}

    def test_availability_respected(self):
        """Worker 1 is unavailable for all shifts; they must not be assigned."""
        num_workers, num_days, num_shifts = 3, 2, 2
        availability = full_availability(num_workers, num_days, num_shifts)
        # Block Worker 1 (index 0) entirely
        availability[0] = [[False, False], [False, False]]

        payload = make_payload(
            num_workers=num_workers,
            num_days=num_days,
            num_shifts=num_shifts,
            min_shifts_per_worker=0,
            max_shifts_per_worker=4,
            demand=[[1, 1], [1, 1]],
            availability=availability,
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("OPTIMAL", "FEASIBLE")
        assert all(a["worker"] != "Worker 1" for a in data["assignments"])

    def test_partial_availability(self):
        """Solver must not assign a worker to a shift they are unavailable for."""
        num_workers, num_days, num_shifts = 3, 2, 2
        availability = full_availability(num_workers, num_days, num_shifts)
        # Worker 2 unavailable for Day 2 Shift 1 (index [1][1][0])
        availability[1][1][0] = False

        payload = make_payload(
            num_workers=num_workers,
            num_days=num_days,
            num_shifts=num_shifts,
            min_shifts_per_worker=0,
            max_shifts_per_worker=4,
            availability=availability,
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("OPTIMAL", "FEASIBLE")
        for a in data["assignments"]:
            if a["worker"] == "Worker 2":
                assert not (a["day"] == 2 and a["shift"] == 1), (
                    "Worker 2 was assigned to blocked day 2 shift 1"
                )

    def test_zero_demand_produces_no_assignments_for_that_slot(self):
        """Slots with demand 0 must have no workers assigned."""
        payload = make_payload(
            num_workers=3,
            num_days=2,
            num_shifts=2,
            min_shifts_per_worker=0,
            max_shifts_per_worker=4,
            demand=[[0, 1], [1, 0]],
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("OPTIMAL", "FEASIBLE")
        for a in data["assignments"]:
            assert not (a["day"] == 1 and a["shift"] == 1)
            assert not (a["day"] == 2 and a["shift"] == 2)

    def test_fairness_objective_distributes_shifts(self):
        """The max shifts assigned to any worker should equal the min possible."""
        num_workers, num_days, num_shifts = 3, 3, 1
        # 3 days × 1 shift × demand 1 = 3 assignments for 3 workers → 1 each
        payload = make_payload(
            num_workers=num_workers,
            num_days=num_days,
            num_shifts=num_shifts,
            min_shifts_per_worker=0,
            max_shifts_per_worker=3,
            demand=[[1], [1], [1]],
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "OPTIMAL"
        assert max(data["shifts_per_worker"].values()) == 1

    def test_omitting_demand_defaults_to_one_per_slot(self):
        """When demand is not provided, every slot should have exactly 1 worker."""
        payload = {
            "num_workers": 2,
            "num_days": 2,
            "num_shifts": 1,
            "min_shifts_per_worker": 1,
            "max_shifts_per_worker": 2,
        }
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("OPTIMAL", "FEASIBLE")
        # 2 days × 1 shift × demand 1 = 2 assignments
        assert len(data["assignments"]) == 2


# ---------------------------------------------------------------------------
# Infeasible problems
# ---------------------------------------------------------------------------

class TestSolveInfeasible:
    def test_impossible_min_shifts_returns_infeasible(self):
        """If total demand can't satisfy min shifts for every worker, solver gives INFEASIBLE."""
        payload = make_payload(
            num_workers=5,
            num_days=1,
            num_shifts=1,
            min_shifts_per_worker=2,  # impossible: only 1 slot total
            max_shifts_per_worker=5,
            demand=[[1]],
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("INFEASIBLE", "MODEL_INVALID", "UNKNOWN")
        assert data["assignments"] == []
        assert data["shifts_per_worker"] == {}

    def test_availability_makes_demand_unsatisfiable(self):
        """Blocking all workers from a required slot produces INFEASIBLE."""
        num_workers, num_days, num_shifts = 2, 1, 1
        # Both workers unavailable for the only slot
        availability = [[[False]], [[False]]]
        payload = make_payload(
            num_workers=num_workers,
            num_days=num_days,
            num_shifts=num_shifts,
            min_shifts_per_worker=0,
            max_shifts_per_worker=1,
            demand=[[1]],
            availability=availability,
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] in ("INFEASIBLE", "MODEL_INVALID", "UNKNOWN")


# ---------------------------------------------------------------------------
# Validation errors (422)
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_min_greater_than_max_shifts(self):
        payload = make_payload(min_shifts_per_worker=5, max_shifts_per_worker=3)
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_worker_names_wrong_length(self):
        payload = make_payload(worker_names=["Alice", "Bob"])  # only 2 for 3 workers
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_availability_wrong_worker_count(self):
        payload = make_payload(
            num_workers=3,
            availability=full_availability(2, 2, 2),  # 2 workers instead of 3
        )
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_availability_wrong_day_count(self):
        # 3 workers, but each has 1 day instead of 2
        availability = [[[True, True]] for _ in range(3)]
        payload = make_payload(availability=availability)
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_availability_wrong_shift_count(self):
        # 3 workers × 2 days × 1 shift instead of 2
        availability = [[[True], [True]] for _ in range(3)]
        payload = make_payload(availability=availability)
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_demand_wrong_day_count(self):
        payload = make_payload(num_days=2, demand=[[1, 1]])  # only 1 day row
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_demand_wrong_shift_count(self):
        payload = make_payload(num_shifts=2, demand=[[1], [1]])  # only 1 shift per row
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_negative_demand_rejected(self):
        payload = make_payload(demand=[[-1, 1], [1, 1]])
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_demand_exceeds_num_workers(self):
        # demand of 5 on one slot but only 3 workers
        payload = make_payload(num_workers=3, demand=[[5, 1], [1, 1]])
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_total_daily_demand_exceeds_num_workers(self):
        # 3 workers, demand [2, 2] on a day → total 4 > 3
        payload = make_payload(num_workers=3, demand=[[2, 2], [1, 1]])
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_zero_workers_rejected_by_schema(self):
        payload = make_payload(num_workers=0)
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_zero_shifts_rejected_by_schema(self):
        payload = make_payload(num_shifts=0)
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_zero_days_rejected_by_schema(self):
        payload = make_payload(num_days=0)
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_negative_min_shifts_rejected_by_schema(self):
        payload = make_payload(min_shifts_per_worker=-1)
        response = client.post("/solve", json=payload)
        assert response.status_code == 422

    def test_too_many_workers_rejected_by_schema(self):
        payload = make_payload(num_workers=51, demand=[[1, 1], [1, 1]])
        response = client.post("/solve", json=payload)
        assert response.status_code == 422
