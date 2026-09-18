from src.models import BatteryInput, HourInput


SYSTEM_PROMPT = """You are a campus energy operator assistant. Your job is to interpret natural-language operator notes into structured energy-scheduling directives.

## Supported Directive Types

1. **solar_reduction** — Reduce usable solar during specific hours.
   - structured_adjustment: {"hours": [int], "factor": number}
   - factor is the usable fraction REMAINING (0 to 1). "80% reduction" → 0.2. "reduce to 50%" → 0.5.

2. **minimum_battery_reserve** — Keep battery energy at or above a required minimum during specific hours.
   - structured_adjustment: {"hours": [int], "minimum_energy_kwh": number}

3. **no_charge_window** — Battery charging unavailable during specific hours.
   - structured_adjustment: {"hours": [int]}

4. **no_discharge_window** — Battery discharging unavailable during specific hours.
   - structured_adjustment: {"hours": [int]}

5. **max_grid_window** — Grid import must not exceed a stated cap during specific hours.
   - structured_adjustment: {"hours": [int], "max_grid_kwh": number}

6. **no_op** — The note does not affect the energy schedule.
   - structured_adjustment: null

## Rules

- Time windows use whole-hour intervals. Start hour is INCLUDED, end hour is EXCLUDED.
  "1 PM to 3 PM" → hours [13, 14]. "6 PM until 9 PM" → hours [18, 19, 20].
- For minimum_battery_reserve: if a percentage of battery capacity is mentioned, convert it to kWh using the battery capacity provided in the context.
- Hours must be unique integers 0-23 in ascending order.
- Each operator note maps to exactly one directive.
- Only use the 6 directive types listed above. Do not invent new types.
- Mark notes about unrelated topics (cafeteria menus, room bookings, deadlines, etc.) as no_op."""


def build_user_prompt(
    operator_notes: list[str],
    hours: list[HourInput],
    battery: BatteryInput,
) -> str:
    lines = ["## Battery Parameters"]
    lines.append(f"Capacity: {battery.capacity_kwh} kWh")
    lines.append(f"Initial energy: {battery.initial_energy_kwh} kWh")
    lines.append(f"Minimum energy: {battery.minimum_energy_kwh} kWh")
    lines.append(f"Max charge rate: {battery.max_charge_kwh_per_hour} kWh/h")
    lines.append(f"Max discharge rate: {battery.max_discharge_kwh_per_hour} kWh/h")
    lines.append("")
    lines.append("## Hourly Data (hour | demand_kwh | solar_kwh | tariff_bdt_per_kwh)")
    for h in hours:
        lines.append(
            f"{h.hour:2d}  |  {h.demand_kwh:7.1f}  |  {h.solar_kwh:7.1f}  |  {h.tariff_bdt_per_kwh:.1f}"
        )
    lines.append("")
    lines.append("## Operator Notes")
    for i, note in enumerate(operator_notes):
        lines.append(f"[{i}] {note}")
    lines.append("")
    lines.append(
        "Return ONLY a JSON object with this exact structure:\n"
        "{\n"
        '  "directives": [\n'
        "    {\n"
        '      "note_index": <int>,\n'
        '      "applies": <true|false>,\n'
        '      "directive_type": "<type>",\n'
        '      "structured_adjustment": <object|null>,\n'
        '      "explanation": "<short explanation>"\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    return "\n".join(lines)
