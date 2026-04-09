# Labour Scheduling

A small optimisation app that builds fair worker shift schedules.

The project includes:

- A `FastAPI` backend that solves the scheduling problem with Google OR-Tools CP-SAT.
- A `Streamlit` frontend to configure workers, demand, and availability.

## Features

- Configurable workforce size, planning horizon, and shifts per day.
- Per-shift demand matrix (`day x shift`).
- Per-worker availability matrix (`worker x day x shift`).
- Hard constraints:
	- Shift coverage must match demand.
	- A worker can work at most one shift per day.
	- Worker total shifts are bounded by min/max limits.
- Fairness objective:
	- Minimises the maximum number of shifts assigned to any worker.

## Tech Stack

- Python `>=3.14`
- FastAPI + Uvicorn (API)
- Streamlit (UI)
- OR-Tools CP-SAT (solver)
- Pandas (table rendering)
- Requests (frontend -> backend communication)

## Project Structure

```text
src/labour_scheduling/
	api.py   # FastAPI service and CP-SAT model
	app.py   # Streamlit UI
tests/
```

## Getting Started

### 1. Install dependencies

This project uses Poetry.

```bash
poetry install
```

### 2. Start the API

```bash
poetry run uvicorn labour_scheduling.api:app --reload
```

The API will run on `http://127.0.0.1:8000`.

### 3. Start the Streamlit app

In a second terminal:

```bash
poetry run streamlit run src/labour_scheduling/app.py
```

Open the URL shown by Streamlit (typically `http://localhost:8501`).

## How It Works

1. Configure workers, days, shifts, min/max shifts, demand, and availability in Streamlit.
2. Click **Solve**.
3. The frontend sends a POST request to `POST /solve`.
4. The backend builds and solves a CP-SAT model.
5. The UI displays:
	 - a schedule grid (`Day x Shift -> Worker(s)`)
	 - a shifts-per-worker bar chart

## API

### Health check

`GET /health`

Response:

```json
{ "status": "ok" }
```

### Solve schedule

`POST /solve`

Example request:

```json
{
	"num_workers": 5,
	"num_days": 7,
	"num_shifts": 3,
	"min_shifts_per_worker": 3,
	"max_shifts_per_worker": 7,
	"demand": [
		[1, 1, 1],
		[1, 1, 1],
		[1, 1, 1],
		[1, 1, 1],
		[1, 1, 1],
		[1, 1, 1],
		[1, 1, 1]
	],
	"availability": [
		[[true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true]],
		[[true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true]],
		[[true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true]],
		[[true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true]],
		[[true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true], [true, true, true]]
	],
	"worker_names": ["Alice", "Bob", "Carol", "Dan", "Eve"]
}
```

Example response:

```json
{
	"status": "OPTIMAL",
	"assignments": [
		{ "worker": "Alice", "day": 1, "shift": 1 },
		{ "worker": "Bob", "day": 1, "shift": 2 }
	],
	"shifts_per_worker": {
		"Alice": 4,
		"Bob": 4,
		"Carol": 4,
		"Dan": 4,
		"Eve": 5
	}
}
```

Possible `status` values:

- `OPTIMAL`
- `FEASIBLE`
- `INFEASIBLE`
- `MODEL_INVALID`
- `UNKNOWN`

## Validation Rules

The backend returns `422` for invalid input, including:

- `min_shifts_per_worker > max_shifts_per_worker`
- `worker_names` length not equal to `num_workers`
- wrong `demand` or `availability` dimensions
- negative demand values
- demand for a shift exceeding `num_workers`
- total daily demand exceeding `num_workers`

## Notes

- The Streamlit app expects the API at `http://127.0.0.1:8000`.
- Solver time limit is currently set to 30 seconds.

## License

No license file is currently included. Add a `LICENSE` file if you plan to distribute this project.
