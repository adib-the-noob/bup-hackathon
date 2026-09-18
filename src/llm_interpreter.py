import json
import os

from openai import OpenAI

from src.guardrails import validate_directives
from src.models import BatteryInput, HourInput
from src.prompt import SYSTEM_PROMPT, build_user_prompt

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["OPENAI_API_KEY"],
        )
    return _client


def interpret_notes(
    operator_notes: list[str],
    hours: list[HourInput],
    battery: BatteryInput,
) -> tuple[list[dict], list[dict]]:
    """Interpret operator notes using an LLM.

    Returns (validated_interpretation_entries, raw_directives_for_optimizer).
    """
    model = os.environ["OPENAI_MODEL"]
    user_prompt = build_user_prompt(operator_notes, hours, battery)

    try:
        response = _get_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw_text = response.choices[0].message.content or ""
        parsed = json.loads(raw_text)
    except Exception:
        return _all_no_op(operator_notes), []

    raw_directives = parsed.get("directives", [])
    if not isinstance(raw_directives, list):
        return _all_no_op(operator_notes), []

    optimizer_directives = validate_directives(
        raw_directives,
        num_notes=len(operator_notes),
        battery_capacity=battery.capacity_kwh,
    )

    # Build interpretation entries for the response
    raw_by_index = {d.get("note_index"): d for d in raw_directives if isinstance(d.get("note_index"), int)}
    interpretation_entries = []
    for i in range(len(operator_notes)):
        optimizer_dir = optimizer_directives[i]
        raw_entry = raw_by_index.get(i, {})
        if optimizer_dir.directive_type == "no_op":
            interpretation_entries.append({
                "note_index": i,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": raw_entry.get(
                    "explanation",
                    "This note does not affect the energy schedule.",
                ),
            })
        else:
            adjustment = _build_adjustment(optimizer_dir)
            interpretation_entries.append({
                "note_index": i,
                "applies": True,
                "directive_type": optimizer_dir.directive_type,
                "structured_adjustment": adjustment,
                "explanation": raw_entry.get(
                    "explanation",
                    f"Applied {optimizer_dir.directive_type} directive.",
                ),
            })

    return interpretation_entries, optimizer_directives


def _build_adjustment(d) -> dict:
    if d.directive_type == "solar_reduction":
        return {"hours": d.hours, "factor": d.factor}
    elif d.directive_type == "minimum_battery_reserve":
        return {"hours": d.hours, "minimum_energy_kwh": d.minimum_energy_kwh}
    elif d.directive_type == "no_charge_window":
        return {"hours": d.hours}
    elif d.directive_type == "no_discharge_window":
        return {"hours": d.hours}
    elif d.directive_type == "max_grid_window":
        return {"hours": d.hours, "max_grid_kwh": d.max_grid_kwh}
    return None


def _all_no_op(operator_notes: list[str]) -> list[dict]:
    return [
        {
            "note_index": i,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "This note does not affect the energy schedule.",
        }
        for i in range(len(operator_notes))
    ]
