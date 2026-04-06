"""FastAPI backend that solves a labour scheduling problem using OR-Tools CP-SAT."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from ortools.sat.python import cp_model

app = FastAPI(title="Labour Scheduling API")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    num_workers: int = Field(..., ge=1, le=50, description="Number of workers")
    num_days: int = Field(..., ge=1, le=31, description="Number of days to schedule")
    num_shifts: int = Field(..., ge=1, le=5, description="Number of shifts per day")
    min_shifts_per_worker: int = Field(..., ge=0, description="Min shifts each worker must cover")
    max_shifts_per_worker: int = Field(..., ge=1, description="Max shifts each worker may cover")
    demand: list[list[int]] | None = Field(
        default=None,
        description="Optional staffing demand grid [day][shift]",
    )
    # availability[worker][day][shift] = True means the worker is available
    # If omitted, all workers are assumed fully available.
    availability: list[list[list[bool]]] | None = Field(
        default=None,
        description="Optional availability grid [worker][day][shift]",
    )
    worker_names: list[str] | None = Field(
        default=None,
        description="Optional list of worker names (length must equal num_workers)",
    )


class ShiftAssignment(BaseModel):
    worker: str
    day: int
    shift: int


class ScheduleResponse(BaseModel):
    status: str  # "OPTIMAL", "FEASIBLE", or "INFEASIBLE"
    assignments: list[ShiftAssignment]
    shifts_per_worker: dict[str, int]


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def _build_worker_names(num_workers: int, names: list[str] | None) -> list[str]:
    if names and len(names) == num_workers:
        return names
    return [f"Worker {i + 1}" for i in range(num_workers)]


def _build_demand(req: ScheduleRequest) -> list[list[int]]:
    if req.demand is None:
        return [[1 for _ in range(req.num_shifts)] for _ in range(req.num_days)]
    return req.demand


def _validate_availability_shape(req: ScheduleRequest) -> None:
    if req.availability is None:
        return
    if len(req.availability) != req.num_workers:
        raise HTTPException(
            status_code=422,
            detail="availability must contain one entry per worker",
        )
    for worker_availability in req.availability:
        if len(worker_availability) != req.num_days:
            raise HTTPException(
                status_code=422,
                detail="availability must contain one day entry per day",
            )
        for day_availability in worker_availability:
            if len(day_availability) != req.num_shifts:
                raise HTTPException(
                    status_code=422,
                    detail="availability must contain one shift entry per shift",
                )


def _validate_demand(req: ScheduleRequest) -> list[list[int]]:
    demand = _build_demand(req)
    if len(demand) != req.num_days:
        raise HTTPException(
            status_code=422,
            detail="demand must contain one row per day",
        )

    for day_index, day_demand in enumerate(demand, start=1):
        if len(day_demand) != req.num_shifts:
            raise HTTPException(
                status_code=422,
                detail="demand must contain one value per shift",
            )
        if any(value < 0 for value in day_demand):
            raise HTTPException(
                status_code=422,
                detail="demand values must be non-negative",
            )
        if any(value > req.num_workers for value in day_demand):
            raise HTTPException(
                status_code=422,
                detail="demand values cannot exceed the number of workers",
            )
        if sum(day_demand) > req.num_workers:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"total demand on day {day_index} exceeds the number of workers "
                    "available for that day"
                ),
            )

    return demand


def solve_schedule(req: ScheduleRequest) -> ScheduleResponse:
    worker_names = _build_worker_names(req.num_workers, req.worker_names)
    demand = _build_demand(req)
    model = cp_model.CpModel()

    # shifts[(w, d, s)] = 1 if worker w works shift s on day d
    shifts: dict[tuple[int, int, int], cp_model.IntVar] = {}
    for w in range(req.num_workers):
        for d in range(req.num_days):
            for s in range(req.num_shifts):
                shifts[(w, d, s)] = model.new_bool_var(f"shift_w{w}_d{d}_s{s}")

    # Availability constraints
    if req.availability:
        for w in range(req.num_workers):
            for d in range(req.num_days):
                for s in range(req.num_shifts):
                    if not req.availability[w][d][s]:
                        model.add(shifts[(w, d, s)] == 0)

    # Each shift on each day is covered by the requested demand
    for d in range(req.num_days):
        for s in range(req.num_shifts):
            model.add(
                sum(shifts[(w, d, s)] for w in range(req.num_workers)) == demand[d][s]
            )

    # Each worker works at most one shift per day
    for w in range(req.num_workers):
        for d in range(req.num_days):
            model.add_at_most_one(shifts[(w, d, s)] for s in range(req.num_shifts))

    # Total shifts per worker within [min, max]
    for w in range(req.num_workers):
        total = sum(shifts[(w, d, s)] for d in range(req.num_days) for s in range(req.num_shifts))
        model.add(total >= req.min_shifts_per_worker)
        model.add(total <= req.max_shifts_per_worker)

    # Objective: minimise the maximum number of shifts assigned to any worker (fairness)
    max_shifts = model.new_int_var(0, req.num_days * req.num_shifts, "max_shifts")
    for w in range(req.num_workers):
        total = sum(shifts[(w, d, s)] for d in range(req.num_days) for s in range(req.num_shifts))
        model.add(max_shifts >= total)
    model.minimize(max_shifts)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status_code = solver.solve(model)

    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    status_str = status_map.get(status_code, "UNKNOWN")

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ScheduleResponse(status=status_str, assignments=[], shifts_per_worker={})

    assignments: list[ShiftAssignment] = []
    shifts_per_worker: dict[str, int] = {name: 0 for name in worker_names}

    for w in range(req.num_workers):
        for d in range(req.num_days):
            for s in range(req.num_shifts):
                if solver.value(shifts[(w, d, s)]):
                    name = worker_names[w]
                    assignments.append(ShiftAssignment(worker=name, day=d + 1, shift=s + 1))
                    shifts_per_worker[name] += 1

    return ScheduleResponse(
        status=status_str,
        assignments=assignments,
        shifts_per_worker=shifts_per_worker,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/solve", response_model=ScheduleResponse)
def solve(req: ScheduleRequest) -> ScheduleResponse:
    """Solve the labour scheduling problem and return a shift assignment."""
    if req.min_shifts_per_worker > req.max_shifts_per_worker:
        raise HTTPException(
            status_code=422,
            detail="min_shifts_per_worker must be <= max_shifts_per_worker",
        )
    if req.worker_names and len(req.worker_names) != req.num_workers:
        raise HTTPException(
            status_code=422,
            detail="Length of worker_names must equal num_workers",
        )
    _validate_availability_shape(req)
    _validate_demand(req)
    return solve_schedule(req)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
