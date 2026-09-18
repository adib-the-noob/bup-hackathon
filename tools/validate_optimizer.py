"""Validate the LP optimizer against sample cases using expected directives."""
import json

from src.guardrails import ValidatedDirective
from src.models import BatteryInput, HourInput
from src.optimizer import solve


def load_samples():
    with open("problem_statement/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json") as f:
        return json.load(f)


def make_directives(interp_list, capacity):
    directives = []
    for entry in interp_list:
        if not entry["applies"] or entry["directive_type"] == "no_op":
            continue
        adj = entry["structured_adjustment"]
        dt = entry["directive_type"]
        if dt == "solar_reduction":
            directives.append(ValidatedDirective(
                directive_type=dt,
                hours=adj["hours"],
                factor=adj["factor"],
            ))
        elif dt == "minimum_battery_reserve":
            directives.append(ValidatedDirective(
                directive_type=dt,
                hours=adj["hours"],
                minimum_energy_kwh=adj["minimum_energy_kwh"],
            ))
        elif dt == "no_charge_window":
            directives.append(ValidatedDirective(
                directive_type=dt,
                hours=adj["hours"],
            ))
        elif dt == "no_discharge_window":
            directives.append(ValidatedDirective(
                directive_type=dt,
                hours=adj["hours"],
            ))
        elif dt == "max_grid_window":
            directives.append(ValidatedDirective(
                directive_type=dt,
                hours=adj["hours"],
                max_grid_kwh=adj["max_grid_kwh"],
            ))
    return directives


def replay_check(case, plan):
    battery = case["input"]["battery"]
    hours_map = {h["hour"]: h for h in case["input"]["hours"]}
    initial_e = battery["initial_energy_kwh"]
    min_e = battery["minimum_energy_kwh"]
    cap_e = battery["capacity_kwh"]
    max_c = battery["max_charge_kwh_per_hour"]
    max_d = battery["max_discharge_kwh_per_hour"]

    errors = []
    e_before = initial_e

    for entry in plan:
        h = entry.hour
        hd = hours_map[h]

        if entry.solar_used_kwh > hd["solar_kwh"] + 0.01:
            errors.append(f"H{h}: solar_used {entry.solar_used_kwh:.2f} > available {hd['solar_kwh']}")

        discharge = entry.battery_kwh if entry.battery_action == "discharge" else 0
        charge = entry.battery_kwh if entry.battery_action == "charge" else 0
        balance = entry.grid_kwh + entry.solar_used_kwh + discharge - hd["demand_kwh"] - charge
        if abs(balance) > 0.02:
            errors.append(f"H{h}: energy balance {balance:.4f}")

        expected_e = e_before + charge - discharge
        if abs(entry.battery_energy_after_kwh - expected_e) > 0.02:
            errors.append(f"H{h}: battery state {entry.battery_energy_after_kwh:.2f} != expected {expected_e:.2f}")

        if entry.battery_energy_after_kwh < min_e - 0.01:
            errors.append(f"H{h}: battery below min ({entry.battery_energy_after_kwh:.2f} < {min_e})")
        if entry.battery_energy_after_kwh > cap_e + 0.01:
            errors.append(f"H{h}: battery above cap ({entry.battery_energy_after_kwh:.2f} > {cap_e})")

        if entry.battery_action == "charge" and entry.battery_kwh > max_c + 0.01:
            errors.append(f"H{h}: charge rate {entry.battery_kwh:.2f} > max {max_c}")
        if entry.battery_action == "discharge" and entry.battery_kwh > max_d + 0.01:
            errors.append(f"H{h}: discharge rate {entry.battery_kwh:.2f} > max {max_d}")
        if entry.battery_action == "idle" and entry.battery_kwh > 0.01:
            errors.append(f"H{h}: idle but battery_kwh={entry.battery_kwh}")

        if entry.grid_kwh < -0.01:
            errors.append(f"H{h}: negative grid {entry.grid_kwh}")

        e_before = entry.battery_energy_after_kwh

    if abs(e_before - initial_e) > 0.02:
        errors.append(f"End-of-day: {e_before:.2f} != initial {initial_e}")

    return errors


def main():
    data = load_samples()
    passed = 0
    failed = 0

    for case in data["cases"]:
        cid = case["id"]
        inp = case["input"]
        expected = case["expected_output"]

        hours = [HourInput(**h) for h in inp["hours"]]
        battery = BatteryInput(**inp["battery"])
        directives = make_directives(expected["directive_interpretation"], battery.capacity_kwh)

        try:
            plan, total_grid, total_cost, peak_grid, summary = solve(hours, battery, directives)
            errors = replay_check(case, plan)

            # Check totals match expected (within tolerance)
            exp_grid = expected["total_grid_kwh"]
            exp_cost = expected["total_cost_bdt"]
            exp_peak = expected["peak_grid_kwh"]

            if abs(total_grid - exp_grid) > 1.0:
                errors.append(f"total_grid_kwh: {total_grid:.2f} vs expected {exp_grid}")
            if abs(total_cost - exp_cost) > 10.0:
                errors.append(f"total_cost_bdt: {total_cost:.2f} vs expected {exp_cost}")
            if abs(peak_grid - exp_peak) > 1.0:
                errors.append(f"peak_grid_kwh: {peak_grid:.2f} vs expected {exp_peak}")

            if errors:
                print(f"{cid}: FAIL")
                for e in errors:
                    print(f"  - {e}")
                failed += 1
            else:
                print(f"{cid}: PASS (cost={total_cost:.2f}, expected={exp_cost})")
                passed += 1
        except Exception as e:
            print(f"{cid}: ERROR - {e}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed out of {passed + failed}")


if __name__ == "__main__":
    main()
