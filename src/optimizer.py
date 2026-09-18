import numpy as np
from scipy.optimize import linprog
from src.models import BatteryInput, HourInput, HourlyPlanEntry
from src.guardrails import ValidatedDirective


def solve(
    hours: list[HourInput],
    battery: BatteryInput,
    directives: list[ValidatedDirective],
) -> tuple[list[HourlyPlanEntry], float, float, float, str]:
    n = 24
    assert len(hours) == n

    demand = np.array([h.demand_kwh for h in hours])
    base_solar = np.array([h.solar_kwh for h in hours])
    tariff = np.array([h.tariff_bdt_per_kwh for h in hours])

    effective_solar = base_solar.copy()
    active_min = np.full(n, battery.minimum_energy_kwh)

    no_charge_hours = set()
    no_discharge_hours = set()
    max_grid_limits: dict[int, float] = {}

    applied_directives = []

    for d in directives:
        if d.directive_type == "solar_reduction":
            for h in d.hours:
                effective_solar[h] = base_solar[h] * d.factor
            applied_directives.append(
                f"Solar reduced to {d.factor*100:.0f}% for hours {d.hours}"
            )
        elif d.directive_type == "minimum_battery_reserve":
            for h in d.hours:
                active_min[h] = max(active_min[h], d.minimum_energy_kwh)
            applied_directives.append(
                f"Battery reserve >= {d.minimum_energy_kwh} kWh for hours {d.hours}"
            )
        elif d.directive_type == "no_charge_window":
            no_charge_hours.update(d.hours)
            applied_directives.append(f"No charging for hours {d.hours}")
        elif d.directive_type == "no_discharge_window":
            no_discharge_hours.update(d.hours)
            applied_directives.append(f"No discharging for hours {d.hours}")
        elif d.directive_type == "max_grid_window":
            for h in d.hours:
                max_grid_limits[h] = d.max_grid_kwh
            applied_directives.append(
                f"Grid capped at {d.max_grid_kwh} kWh for hours {d.hours}"
            )

    # Variable layout: [g0..g23, s0..s23, c0..c23, d0..d23]
    # Indices: g[h] = h, s[h] = n+h, c[h] = 2n+h, d[h] = 3n+h

    # Objective
    c_obj = np.zeros(4 * n)
    c_obj[:n] = tariff

    # Equality constraints: A_eq @ x = b_eq
    A_eq = []
    b_eq = []

    # 1. Energy balance: g[h] + s[h] + d[h] - c[h] = demand[h]
    for h in range(n):
        row = np.zeros(4 * n)
        row[h] = 1.0
        row[n + h] = 1.0
        row[3 * n + h] = 1.0
        row[2 * n + h] = -1.0
        A_eq.append(row)
        b_eq.append(demand[h])

    # 2. End-of-day neutrality: sum(c) - sum(d) = 0
    row = np.zeros(4 * n)
    for h in range(n):
        row[2 * n + h] = 1.0
        row[3 * n + h] = -1.0
    A_eq.append(row)
    b_eq.append(0.0)

    # Inequality constraints: A_ub @ x <= b_ub
    A_ub = []
    b_ub = []

    # 1. Solar: s[h] <= effective_solar[h]
    for h in range(n):
        row = np.zeros(4 * n)
        row[n + h] = 1.0
        A_ub.append(row)
        b_ub.append(effective_solar[h])

    # 2. Charge rate: c[h] <= max_charge
    for h in range(n):
        row = np.zeros(4 * n)
        row[2 * n + h] = 1.0
        A_ub.append(row)
        b_ub.append(battery.max_charge_kwh_per_hour)

    # 3. Discharge rate: d[h] <= max_discharge
    for h in range(n):
        row = np.zeros(4 * n)
        row[3 * n + h] = 1.0
        A_ub.append(row)
        b_ub.append(battery.max_discharge_kwh_per_hour)

    # 4. Battery lower bound: initial + sum(c[0..h]) - sum(d[0..h]) >= active_min[h]
    # => -sum(c[0..h]) + sum(d[0..h]) <= initial - active_min[h]
    for h in range(n):
        row = np.zeros(4 * n)
        for k in range(h + 1):
            row[2 * n + k] = -1.0
            row[3 * n + k] = 1.0
        A_ub.append(row)
        b_ub.append(battery.initial_energy_kwh - active_min[h])

    # 5. Battery upper bound: sum(c[0..h]) - sum(d[0..h]) <= capacity - initial
    for h in range(n):
        row = np.zeros(4 * n)
        for k in range(h + 1):
            row[2 * n + k] = 1.0
            row[3 * n + k] = -1.0
        A_ub.append(row)
        b_ub.append(battery.capacity_kwh - battery.initial_energy_kwh)

    # 6. no_charge_window: c[h] <= 0 (c already >= 0 by bounds)
    for h in no_charge_hours:
        row = np.zeros(4 * n)
        row[2 * n + h] = 1.0
        A_ub.append(row)
        b_ub.append(0.0)

    # 7. no_discharge_window: d[h] <= 0
    for h in no_discharge_hours:
        row = np.zeros(4 * n)
        row[3 * n + h] = 1.0
        A_ub.append(row)
        b_ub.append(0.0)

    # 8. max_grid_window: g[h] <= max_grid_kwh
    for h, cap in max_grid_limits.items():
        row = np.zeros(4 * n)
        row[h] = 1.0
        A_ub.append(row)
        b_ub.append(cap)

    # Variable bounds
    bounds = [(0.0, None)] * (4 * n)

    result = linprog(
        c=c_obj,
        A_ub=np.array(A_ub),
        b_ub=np.array(b_ub),
        A_eq=np.array(A_eq),
        b_eq=np.array(b_eq),
        bounds=bounds,
        method="highs",
    )

    if not result.success:
        raise RuntimeError("Optimization failed: the given scenario and directives are infeasible.")

    x = result.x
    g = np.where(np.abs(x[:n]) < 1e-9, 0.0, x[:n])
    s = np.where(np.abs(x[n : 2 * n]) < 1e-9, 0.0, x[n : 2 * n])
    c_arr = np.where(np.abs(x[2 * n : 3 * n]) < 1e-9, 0.0, x[2 * n : 3 * n])
    d_arr = np.where(np.abs(x[3 * n : 4 * n]) < 1e-9, 0.0, x[3 * n : 4 * n])

    # Net charge/discharge per hour so a single hour never reports an
    # internally inconsistent pair of actions.
    net = c_arr - d_arr

    plan = []
    e_prev = battery.initial_energy_kwh
    for h in range(n):
        e_after = e_prev + net[h]
        if net[h] > 1e-6:
            action = "charge"
            b_kwh = net[h]
        elif net[h] < -1e-6:
            action = "discharge"
            b_kwh = -net[h]
        else:
            action = "idle"
            b_kwh = 0.0

        plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(g[h], 4),
                solar_used_kwh=round(s[h], 4),
                battery_action=action,
                battery_kwh=round(b_kwh, 4),
                battery_energy_after_kwh=round(e_after, 4),
            )
        )
        e_prev = e_after

    total_grid = float(np.sum(g))
    total_cost = float(np.dot(g, tariff))
    peak_grid = float(np.max(g))

    summary_parts = [f"Total cost: {total_cost:.2f} BDT over 24h."]
    if applied_directives:
        summary_parts.append("Applied: " + "; ".join(applied_directives) + ".")
    else:
        summary_parts.append("No operator directives applied.")

    plan_summary = " ".join(summary_parts)

    return plan, total_grid, total_cost, peak_grid, plan_summary
