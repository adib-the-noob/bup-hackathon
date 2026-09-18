"""Validate the deployed API against a case pack.

Handles two pack layouts:
  - dir of N.json + N.expected.json  (input file + expected output file)
  - a single JSON pack with "cases" (public sample style: case.input / case.expected_output)

Usage:
    python -m tools.run_cases [PACK] [BASE_URL]
    PACK    = "tests" (default) or path to a dir or a pack .json file
    BASE_URL= http://localhost:8000  (default)

Uses only the Python standard library.
"""
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request


def post_json(url, payload, timeout=45):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# interpretation comparison
# --------------------------------------------------------------------------- #
def check_interp(case_input, expected_interp, got_interp):
    errors = []
    if len(got_interp) != len(expected_interp):
        errors.append(
            f"interpretation count {len(got_interp)} != expected {len(expected_interp)}"
        )
        return errors

    for i, (got, exp) in enumerate(zip(got_interp, expected_interp)):
        if got.get("note_index") != exp.get("note_index"):
            errors.append(f"note[{i}] index {got.get('note_index')} != {exp.get('note_index')}")
        if got.get("applies") != exp.get("applies"):
            errors.append(f"note[{i}] applies {got.get('applies')} != {exp.get('applies')}")
        if got.get("directive_type") != exp.get("directive_type"):
            errors.append(
                f"note[{i}] type {got.get('directive_type')} != {exp.get('directive_type')}"
            )

        got_adj = got.get("structured_adjustment")
        exp_adj = exp.get("structured_adjustment")
        if exp.get("directive_type") == "no_op":
            if got_adj is not None:
                errors.append(f"note[{i}] no_op must have null adjustment")
            continue
        if not isinstance(got_adj, dict):
            errors.append(f"note[{i}] missing structured_adjustment")
            continue
        for key, val in (exp_adj or {}).items():
            gv = got_adj.get(key)
            if isinstance(val, list):
                if gv != val:
                    errors.append(f"note[{i}] {key}={gv} != expected {val}")
            else:
                if not isinstance(gv, (int, float)) or abs(float(gv) - float(val)) > 0.01:
                    errors.append(f"note[{i}] {key}={gv} != expected {val}")
        extra = set(got_adj) - set(exp_adj or {})
        if extra:
            errors.append(f"note[{i}] unexpected adjustment keys {extra}")
    return errors


# --------------------------------------------------------------------------- #
# deterministic directive application (mirrors the optimizer semantics)
# --------------------------------------------------------------------------- #
def apply_directives(inp, interp):
    hours = {h["hour"]: h for h in inp["hours"]}
    battery = inp["battery"]
    eff_solar = {h: hours[h]["solar_kwh"] for h in range(24)}
    active_min = {h: battery["minimum_energy_kwh"] for h in range(24)}
    no_charge = set()
    no_discharge = set()
    max_grid = {}

    for entry in interp:
        if not entry["applies"] or entry["directive_type"] == "no_op":
            continue
        adj = entry["structured_adjustment"] or {}
        hrs = adj.get("hours", [])
        dt = entry["directive_type"]
        if dt == "solar_reduction":
            factor = float(adj["factor"])
            for h in hrs:
                eff_solar[h] = hours[h]["solar_kwh"] * factor
        elif dt == "minimum_battery_reserve":
            for h in hrs:
                active_min[h] = max(active_min[h], float(adj["minimum_energy_kwh"]))
        elif dt == "no_charge_window":
            no_charge.update(hrs)
        elif dt == "no_discharge_window":
            no_discharge.update(hrs)
        elif dt == "max_grid_window":
            for h in hrs:
                max_grid[h] = float(adj["max_grid_kwh"])

    return eff_solar, active_min, no_charge, no_discharge, max_grid


def replay_check(inp, plan, interp):
    hours = {h["hour"]: h for h in inp["hours"]}
    battery = inp["battery"]
    eff, min_lvl, nc, nd, mg = apply_directives(inp, interp)
    initial_e = battery["initial_energy_kwh"]
    max_c = battery["max_charge_kwh_per_hour"]
    max_d = battery["max_discharge_kwh_per_hour"]

    errors = []
    e = initial_e
    for ent in plan:
        h = ent["hour"]
        if h not in hours:
            errors.append(f"H{h}: hour not present in input")
            continue
        hd = hours[h]
        solar = ent["solar_used_kwh"]; grid = ent["grid_kwh"]
        bk = ent["battery_kwh"]; act = ent["battery_action"]
        after = ent["battery_energy_after_kwh"]

        if solar > eff[h] + 0.01:
            errors.append(f"H{h}: solar_used {solar} > effective {eff[h]}")
        if grid > mg.get(h, float("inf")) + 0.01:
            errors.append(f"H{h}: grid {grid} > cap {mg.get(h)}")

        ch = bk if act == "charge" else 0
        ds = bk if act == "discharge" else 0
        bal = grid + solar + ds - hd["demand_kwh"] - ch
        if abs(bal) > 0.02:
            errors.append(f"H{h}: energy balance {bal:.4f}")
        exp = e + ch - ds
        if abs(after - exp) > 0.02:
            errors.append(f"H{h}: battery state {after} != expected {exp}")

        if after < min_lvl[h] - 0.01:
            errors.append(f"H{h}: battery below reserve {after} < {min_lvl[h]}")
        if after > battery["capacity_kwh"] + 0.01:
            errors.append(f"H{h}: battery above capacity {after}")
        if act == "charge" and bk > max_c + 0.01:
            errors.append(f"H{h}: charge rate {bk} > max {max_c}")
        if act == "discharge" and bk > max_d + 0.01:
            errors.append(f"H{h}: discharge rate {bk} > max {max_d}")
        if act == "idle" and bk > 0.01:
            errors.append(f"H{h}: idle but battery_kwh={bk}")
        if h in nc and act == "charge":
            errors.append(f"H{h}: charge violates no_charge_window")
        if h in nd and act == "discharge":
            errors.append(f"H{h}: discharge violates no_discharge_window")
        if grid < -0.01:
            errors.append(f"H{h}: negative grid {grid}")
        if solar < -0.01:
            errors.append(f"H{h}: negative solar_used {solar}")

        e = after

    if abs(e - initial_e) > 0.02:
        errors.append(f"End-of-day battery {e} != initial {initial_e}")
    return errors


def check_totals(inp, plan, resp):
    hours = {h["hour"]: h for h in inp["hours"]}
    g = sum(h["grid_kwh"] for h in plan)
    c = sum(h["grid_kwh"] * hours[h["hour"]]["tariff_bdt_per_kwh"] for h in plan)
    p = max(h["grid_kwh"] for h in plan)
    errs = []
    if abs(resp["total_grid_kwh"] - g) > 0.02:
        errs.append(f"total_grid_kwh {resp['total_grid_kwh']} vs {g}")
    if abs(resp["total_cost_bdt"] - c) > 0.02:
        errs.append(f"total_cost_bdt {resp['total_cost_bdt']} vs {c}")
    if abs(resp["peak_grid_kwh"] - p) > 0.02:
        errs.append(f"peak_grid_kwh {resp['peak_grid_kwh']} vs {p}")
    return errs


# --------------------------------------------------------------------------- #
# pack loading
# --------------------------------------------------------------------------- #
def load_dir(path):
    """Return list of (cid, input, expected_output)."""
    cases = []
    for inp_path in sorted(glob.glob(os.path.join(path, "*.json"))):
        if inp_path.endswith(".expected.json"):
            continue
        with open(inp_path) as f:
            inp = json.load(f)
        exp_path = inp_path[:-5] + ".expected.json"
        with open(exp_path) as f:
            exp = json.load(f)
        cases.append((inp.get("scenario_id", inp_path), inp, exp))
    return cases


def load_pack(path):
    if os.path.isdir(path):
        return load_dir(path)
    with open(path) as f:
        data = json.load(f)
    if "cases" in data:
        return [(c["id"], c["input"], c["expected_output"]) for c in data["cases"]]
    return load_dir(os.path.dirname(path) or ".")


# --------------------------------------------------------------------------- #
def main():
    pack = sys.argv[1] if len(sys.argv) > 1 else "tests"
    base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"

    try:
        status, health = get_json(f"{base}/health")
        print(f"Health: HTTP {status} {health}   (pack: {pack})")
    except Exception as e:
        print(f"ERROR: cannot reach API at {base}: {e}")
        sys.exit(1)

    cases = load_pack(pack)
    passed = failed = 0

    for cid, inp, exp in cases:
        try:
            t0 = time.time()
            status, resp = post_json(f"{base}/optimize-energy", inp)
            el = time.time() - t0
            if status != 200:
                print(f"{cid}: FAIL (HTTP {status}, {el:.1f}s) -> {resp.get('detail', resp)}")
                failed += 1
                continue

            plan = resp["hourly_plan"]
            got = resp.get("directive_interpretation", [])
            exp_interp = exp["directive_interpretation"]

            errors = []
            errors.extend(check_interp(inp, exp_interp, got))
            # Downstream application: judge replays against GROUND-TRUTH directives
            errors.extend(replay_check(inp, plan, exp_interp))
            # Self-consistency: plan must also obey its own reported interpretation
            errors.extend(replay_check(inp, plan, got))
            errors.extend(check_totals(inp, plan, resp))

            exp_cost = exp.get("total_cost_bdt")
            ratio = "n/a"
            if isinstance(exp_cost, (int, float)) and resp["total_cost_bdt"] > 0:
                ratio = f"{exp_cost / resp['total_cost_bdt']:.4f}"

            if errors:
                print(f"{cid}: FAIL ({el:.1f}s, cost={resp['total_cost_bdt']}, ratio={ratio})")
                for e in errors:
                    print(f"  - {e}")
                failed += 1
            else:
                print(f"{cid}: PASS ({el:.1f}s, cost={resp['total_cost_bdt']}, ratio={ratio})")
                passed += 1
        except Exception as e:
            print(f"{cid}: ERROR ({type(e).__name__}: {e})")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed out of {passed + failed}")


if __name__ == "__main__":
    main()