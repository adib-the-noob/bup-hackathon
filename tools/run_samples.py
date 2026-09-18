"""Validate the API against the public sample case pack.

Usage:
    python -m tools.run_samples.py

Requires the API to be running on localhost:8000.
"""
import json
import sys

import requests

SAMPLES_PATH = "problem_statement/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
BASE_URL = "http://localhost:8000"


def replay_check(case, plan):
    """Re-play the plan to verify GridWise constraints."""
    battery = case["input"]["battery"]
    hours = {h["hour"]: h for h in case["input"]["hours"]}
    initial_e = battery["initial_energy_kwh"]
    min_e = battery["minimum_energy_kwh"]
    cap_e = battery["capacity_kwh"]
    max_c = battery["max_charge_kwh_per_hour"]
    max_d = battery["max_discharge_kwh_per_hour"]

    errors = []
    e_before = initial_e

    for entry in plan:
        h = entry["hour"]
        hd = hours[h]
        solar_used = entry["solar_used_kwh"]
        grid = entry["grid_kwh"]
        action = entry["battery_action"]
        bk = entry["battery_kwh"]
        e_after = entry["battery_energy_after_kwh"]

        # Solar limit
        if solar_used > hd["solar_kwh"] + 0.01:
            errors.append(f"H{h}: solar_used {solar_used} > available {hd['solar_kwh']}")

        # Energy balance
        discharge = bk if action == "discharge" else 0
        charge = bk if action == "charge" else 0
        balance = grid + solar_used + discharge - hd["demand_kwh"] - charge
        if abs(balance) > 0.02:
            errors.append(f"H{h}: energy balance {balance:.4f}")

        # Battery transition
        expected_e = e_before + charge - discharge
        if abs(e_after - expected_e) > 0.02:
            errors.append(f"H{h}: battery state {e_after} != expected {expected_e}")

        # Battery bounds
        if e_after < min_e - 0.01:
            errors.append(f"H{h}: battery below minimum ({e_after} < {min_e})")
        if e_after > cap_e + 0.01:
            errors.append(f"H{h}: battery above capacity ({e_after} > {cap_e})")

        # Rate limits
        if action == "charge" and bk > max_c + 0.01:
            errors.append(f"H{h}: charge rate {bk} > max {max_c}")
        if action == "discharge" and bk > max_d + 0.01:
            errors.append(f"H{h}: discharge rate {bk} > max {max_d}")
        if action == "idle" and bk > 0.01:
            errors.append(f"H{h}: idle but battery_kwh={bk}")

        if grid < -0.01:
            errors.append(f"H{h}: negative grid {grid}")
        if solar_used < -0.01:
            errors.append(f"H{h}: negative solar_used {solar_used}")

        e_before = e_after

    # End-of-day neutrality
    if abs(e_before - initial_e) > 0.02:
        errors.append(f"End-of-day battery {e_before} != initial {initial_e}")

    return errors


def check_totals(case, plan, resp):
    expected_grid = sum(h["grid_kwh"] for h in plan)
    hours = {h["hour"]: h for h in case["input"]["hours"]}
    expected_cost = sum(
        h["grid_kwh"] * hours[h["hour"]]["tariff_bdt_per_kwh"] for h in plan
    )
    expected_peak = max(h["grid_kwh"] for h in plan)

    errors = []
    if abs(resp["total_grid_kwh"] - expected_grid) > 0.02:
        errors.append(
            f"total_grid_kwh mismatch: {resp['total_grid_kwh']} vs {expected_grid}"
        )
    if abs(resp["total_cost_bdt"] - expected_cost) > 0.02:
        errors.append(
            f"total_cost_bdt mismatch: {resp['total_cost_bdt']} vs {expected_cost}"
        )
    if abs(resp["peak_grid_kwh"] - expected_peak) > 0.02:
        errors.append(
            f"peak_grid_kwh mismatch: {resp['peak_grid_kwh']} vs {expected_peak}"
        )
    return errors


def main():
    with open(SAMPLES_PATH) as f:
        data = json.load(f)

    # Health check
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        r.raise_for_status()
        print(f"Health: {r.json()}")
    except Exception as e:
        print(f"ERROR: Cannot reach API at {BASE_URL}: {e}")
        sys.exit(1)

    passed = 0
    failed = 0

    for case in data["cases"]:
        cid = case["id"]
        try:
            r = requests.post(
                f"{BASE_URL}/optimize-energy",
                json=case["input"],
                timeout=30,
            )
            if r.status_code != 200:
                print(f"{cid}: FAIL (HTTP {r.status_code})")
                failed += 1
                continue

            resp = r.json()
            plan = resp["hourly_plan"]

            errors = []
            errors.extend(replay_check(case, plan))
            errors.extend(check_totals(case, plan, resp))

            # Check interpretation (soft check - just count directives)
            interp = resp.get("directive_interpretation", [])
            expected_interp = case["expected_output"]["directive_interpretation"]
            if len(interp) != len(expected_interp):
                errors.append(
                    f"Interpretation count: {len(interp)} vs expected {len(expected_interp)}"
                )

            if errors:
                print(f"{cid}: FAIL")
                for e in errors:
                    print(f"  - {e}")
                failed += 1
            else:
                print(f"{cid}: PASS")
                passed += 1

        except Exception as e:
            print(f"{cid}: ERROR ({e})")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed out of {passed + failed}")


if __name__ == "__main__":
    main()
