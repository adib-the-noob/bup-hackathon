from src.guardrails import ValidatedDirective
from src.models import BatteryInput, HourInput
from src.optimizer import solve


def _make_hours(demands, solars, tariffs):
    return [
        HourInput(hour=h, demand_kwh=d, solar_kwh=s, tariff_bdt_per_kwh=t)
        for h, (d, s, t) in enumerate(zip(demands, solars, tariffs))
    ]


def test_basic_no_directives():
    demands = [100.0] * 24
    solars = [0.0] * 24
    tariffs = [10.0] * 24
    hours = _make_hours(demands, solars, tariffs)
    battery = BatteryInput(
        capacity_kwh=500,
        initial_energy_kwh=200,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=100,
        max_discharge_kwh_per_hour=100,
    )

    plan, total_grid, total_cost, peak_grid, summary = solve(hours, battery, [])

    assert len(plan) == 24
    assert abs(total_grid - 2400.0) < 0.01
    assert abs(total_cost - 24000.0) < 0.01
    # With flat tariff, peak may exceed demand if optimizer charges battery
    assert peak_grid >= 100.0
    # End-of-day neutrality
    assert abs(plan[-1].battery_energy_after_kwh - 200.0) < 0.01


def test_solar_directive():
    demands = [100.0] * 12 + [200.0] * 12
    solars = [0.0] * 6 + [100.0] * 12 + [0.0] * 6
    tariffs = [5.0] * 24
    hours = _make_hours(demands, solars, tariffs)
    battery = BatteryInput(
        capacity_kwh=500,
        initial_energy_kwh=200,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=100,
        max_discharge_kwh_per_hour=100,
    )
    directives = [
        ValidatedDirective(
            directive_type="solar_reduction",
            hours=[10, 11],
            factor=0.2,
        )
    ]

    plan, total_grid, total_cost, peak_grid, summary = solve(hours, battery, directives)

    assert len(plan) == 24
    # With solar reduction, usable solar at hour 10,11 should be 20 instead of 100
    assert plan[10].solar_used_kwh <= 20.0 + 0.01
    assert plan[11].solar_used_kwh <= 20.0 + 0.01
    # End-of-day neutrality
    assert abs(plan[-1].battery_energy_after_kwh - 200.0) < 0.01


def test_no_charge_window():
    demands = [100.0] * 24
    solars = [50.0] * 24
    tariffs = [10.0] * 24
    hours = _make_hours(demands, solars, tariffs)
    battery = BatteryInput(
        capacity_kwh=500,
        initial_energy_kwh=200,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=100,
        max_discharge_kwh_per_hour=100,
    )
    directives = [
        ValidatedDirective(
            directive_type="no_charge_window",
            hours=[2, 3, 4],
        )
    ]

    plan, total_grid, total_cost, peak_grid, summary = solve(hours, battery, directives)

    for h in [2, 3, 4]:
        assert plan[h].battery_action != "charge"
        assert plan[h].battery_kwh == 0 or plan[h].battery_action == "discharge"


def test_max_grid_window():
    demands = [200.0] * 24
    solars = [0.0] * 24
    tariffs = [10.0] * 24
    hours = _make_hours(demands, solars, tariffs)
    battery = BatteryInput(
        capacity_kwh=1000,
        initial_energy_kwh=500,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=200,
        max_discharge_kwh_per_hour=200,
    )
    directives = [
        ValidatedDirective(
            directive_type="max_grid_window",
            hours=[18, 19, 20],
            max_grid_kwh=150.0,
        )
    ]

    plan, total_grid, total_cost, peak_grid, summary = solve(hours, battery, directives)

    for h in [18, 19, 20]:
        assert plan[h].grid_kwh <= 150.0 + 0.01


def test_energy_balance():
    demands = [150.0, 200.0, 180.0] + [100.0] * 21
    solars = [50.0, 0.0, 30.0] + [20.0] * 21
    tariffs = [10.0] * 24
    hours = _make_hours(demands, solars, tariffs)
    battery = BatteryInput(
        capacity_kwh=500,
        initial_energy_kwh=200,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=100,
        max_discharge_kwh_per_hour=100,
    )

    plan, total_grid, total_cost, peak_grid, summary = solve(hours, battery, [])

    for h_entry in plan:
        d = demands[h_entry.hour]
        solar_u = h_entry.solar_used_kwh
        grid = h_entry.grid_kwh
        if h_entry.battery_action == "charge":
            bk = h_entry.battery_kwh
        elif h_entry.battery_action == "discharge":
            bk = -h_entry.battery_kwh
        else:
            bk = 0
        # grid + solar_used + discharge = demand + charge
        # grid + solar_u + max(0, -bk) = d + max(0, bk)
        discharge = max(0, -bk)
        charge = max(0, bk)
        balance = grid + solar_u + discharge - d - charge
        assert abs(balance) < 0.01, f"Energy balance failed at hour {h_entry.hour}"


def test_battery_bounds():
    demands = [100.0] * 24
    solars = [0.0] * 24
    tariffs = [10.0] * 24
    hours = _make_hours(demands, solars, tariffs)
    battery = BatteryInput(
        capacity_kwh=300,
        initial_energy_kwh=150,
        minimum_energy_kwh=50,
        max_charge_kwh_per_hour=80,
        max_discharge_kwh_per_hour=80,
    )

    plan, total_grid, total_cost, peak_grid, summary = solve(hours, battery, [])

    for h_entry in plan:
        assert h_entry.battery_energy_after_kwh >= 50.0 - 0.01
        assert h_entry.battery_energy_after_kwh <= 300.0 + 0.01
