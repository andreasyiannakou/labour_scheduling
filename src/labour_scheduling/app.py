"""Streamlit front-end for the Labour Scheduling solver."""

import requests
import streamlit as st
import pandas as pd

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Labour Scheduling", page_icon="📅", layout="wide")
st.title("📅 Labour Scheduling Solver")
st.caption("Configure your workforce below, then click **Solve** to generate an optimal shift schedule.")

# ---------------------------------------------------------------------------
# Sidebar — problem parameters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Parameters")

    num_workers = st.number_input("Number of workers", min_value=1, max_value=50, value=5)
    num_days = st.number_input("Number of days", min_value=1, max_value=31, value=7)
    num_shifts = st.number_input("Shifts per day", min_value=1, max_value=5, value=3)

    st.divider()

    min_shifts = st.number_input(
        "Min shifts per worker",
        min_value=0,
        max_value=int(num_days * num_shifts),
        value=min(3, int(num_days * num_shifts)),
    )
    max_shifts = st.number_input(
        "Max shifts per worker",
        min_value=1,
        max_value=int(num_days * num_shifts),
        value=min(7, int(num_days * num_shifts)),
    )

    st.divider()
    st.subheader("Worker names (optional)")
    worker_names: list[str] = []
    for i in range(int(num_workers)):
        name = st.text_input(f"Worker {i + 1}", value=f"Worker {i + 1}", key=f"name_{i}")
        worker_names.append(name.strip() or f"Worker {i + 1}")

# ---------------------------------------------------------------------------
# Main area — per-worker availability grids
# ---------------------------------------------------------------------------
shift_labels = [f"Shift {s + 1}" for s in range(int(num_shifts))]
day_labels = [f"Day {d + 1}" for d in range(int(num_days))]

st.subheader("Demand")
st.info("Set the number of workers needed for each day and shift.")

demand_store = st.session_state.setdefault("demand_store", {})

for day_index in range(int(num_days)):
    for shift_index in range(int(num_shifts)):
        demand_key = (day_index, shift_index)
        if demand_key not in demand_store:
            demand_store[demand_key] = 1
        demand_store[demand_key] = min(max(int(demand_store[demand_key]), 0), int(num_workers))

header_columns = st.columns(int(num_shifts) + 1)
header_columns[0].markdown("**Day**")
for shift_index, shift_label in enumerate(shift_labels, start=1):
    header_columns[shift_index].markdown(f"**{shift_label}**")

demand: list[list[int]] = []
for day_index, day_label in enumerate(day_labels):
    row_columns = st.columns(int(num_shifts) + 1)
    row_columns[0].markdown(day_label)

    day_demand: list[int] = []
    for shift_index in range(int(num_shifts)):
        demand_key = (day_index, shift_index)
        with row_columns[shift_index + 1]:
            value = st.number_input(
                label=f"{day_label} {shift_labels[shift_index]}",
                min_value=0,
                max_value=int(num_workers),
                step=1,
                value=int(demand_store[demand_key]),
                key=f"demand_{day_index}_{shift_index}",
                label_visibility="collapsed",
            )
        demand_store[demand_key] = int(value)
        day_demand.append(int(value))

    demand.append(day_demand)

st.subheader("Availability")
st.info(
    "For each worker, tick the cells where they **are available** to work. "
    "All cells are ticked by default."
)

availability_store = st.session_state.setdefault("availability_store", {})

for worker_index in range(int(num_workers)):
    saved_availability = availability_store.get(worker_index)
    if saved_availability is None or len(saved_availability) != int(num_days) or any(
        len(day_availability) != int(num_shifts) for day_availability in saved_availability
    ):
        availability_store[worker_index] = [
            [True for _ in range(int(num_shifts))] for _ in range(int(num_days))
        ]

if st.session_state.get("selected_worker_index", 0) >= int(num_workers):
    st.session_state["selected_worker_index"] = 0

st.selectbox(
    "Worker",
    options=list(range(int(num_workers))),
    format_func=lambda worker_index: worker_names[worker_index],
    key="selected_worker_index",
)

selected_worker_index = st.session_state["selected_worker_index"]
selected_availability = availability_store[selected_worker_index]

avail_df = pd.DataFrame(selected_availability, index=day_labels, columns=shift_labels)
edited_df = st.data_editor(
    avail_df,
    use_container_width=True,
    key=f"avail_editor_{selected_worker_index}",
)

availability_store[selected_worker_index] = [
    [bool(edited_df.loc[d_label, s_label]) for s_label in shift_labels]
    for d_label in day_labels
]

availability: list[list[list[bool]]] = [
    availability_store[worker_index] for worker_index in range(int(num_workers))
]

# ---------------------------------------------------------------------------
# Solve
# ---------------------------------------------------------------------------
if st.button("🚀 Solve", type="primary"):
    if any(value < 0 for day_demand in demand for value in day_demand):
        st.error("Demand values must be zero or greater.")
        st.stop()

    if any(sum(day_demand) > int(num_workers) for day_demand in demand):
        st.error("Total daily demand cannot exceed the number of workers.")
        st.stop()

    payload = {
        "num_workers": int(num_workers),
        "num_days": int(num_days),
        "num_shifts": int(num_shifts),
        "min_shifts_per_worker": int(min_shifts),
        "max_shifts_per_worker": int(max_shifts),
        "demand": demand,
        "availability": availability,
        "worker_names": worker_names,
    }

    with st.spinner("Solving… this may take a few seconds."):
        try:
            response = requests.post(f"{API_URL}/solve", json=payload, timeout=60)
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            st.error(
                "Could not reach the API server. "
                "Start it with: `uvicorn labour_scheduling.api:app --reload`"
            )
            st.stop()
        except requests.exceptions.HTTPError as exc:
            st.error(f"API error {exc.response.status_code}: {exc.response.text}")
            st.stop()

    result = response.json()
    status = result["status"]

    if status in ("INFEASIBLE", "MODEL_INVALID", "UNKNOWN"):
        st.error(
            f"Solver returned **{status}**. Try relaxing your constraints "
            "(fewer required shifts, more workers, or wider availability)."
        )
        st.stop()

    badge = "✅ Optimal" if status == "OPTIMAL" else "⚠️ Feasible (not proven optimal)"
    st.success(f"Solution found — {badge}")

    assignments = result["assignments"]
    shifts_per_worker = result["shifts_per_worker"]

    # ----- Schedule grid -----
    st.subheader("Schedule")

    # Build a pivot: rows = Day, columns = Shift, cell = worker name
    rows: list[dict] = []
    for a in assignments:
        rows.append({"Day": f"Day {a['day']}", "Shift": f"Shift {a['shift']}", "Worker": a["worker"]})

    if rows:
        schedule_df = (
            pd.DataFrame(rows)
            .groupby(["Day", "Shift"], sort=False)["Worker"]
            .agg(", ".join)
            .unstack("Shift")
            .reindex(index=day_labels, columns=shift_labels)
        )
        st.dataframe(schedule_df, use_container_width=True)
    else:
        st.warning("No assignments returned.")

    # ----- Shifts per worker bar chart -----
    st.subheader("Shifts per worker")
    summary_df = pd.DataFrame(
        list(shifts_per_worker.items()), columns=["Worker", "Shifts"]
    ).set_index("Worker")
    st.bar_chart(summary_df)
