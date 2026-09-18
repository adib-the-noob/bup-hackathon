from dataclasses import dataclass, field


ALLOWED_TYPES = frozenset(
    {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    }
)


@dataclass
class ValidatedDirective:
    directive_type: str
    hours: list[int] = field(default_factory=list)
    factor: float | None = None
    minimum_energy_kwh: float | None = None
    max_grid_kwh: float | None = None


def _validate_hours(hours_raw: list, capacity: float) -> list[int] | None:
    """Validate and return sorted unique hours, or None if invalid."""
    if not isinstance(hours_raw, list) or len(hours_raw) == 0:
        return None
    try:
        hours = [int(h) for h in hours_raw]
    except (TypeError, ValueError):
        return None
    if len(hours) != len(set(hours)):
        return None
    if any(h < 0 or h > 23 for h in hours):
        return None
    hours.sort()
    return hours


def validate_directives(
    raw_directives: list[dict],
    num_notes: int,
    battery_capacity: float,
) -> list[ValidatedDirective]:
    """Validate raw LLM output into safe structured directives.

    Any note that fails validation is downgraded to no_op.
    """
    validated: list[ValidatedDirective | None] = [None] * num_notes

    for raw in raw_directives:
        note_index = raw.get("note_index")
        if not isinstance(note_index, int) or note_index < 0 or note_index >= num_notes:
            continue

        directive_type = raw.get("directive_type")
        applies = raw.get("applies", False)
        adjustment = raw.get("structured_adjustment")

        # no_op handling
        if directive_type == "no_op" or not applies:
            validated[note_index] = ValidatedDirective(directive_type="no_op")
            continue

        if directive_type not in ALLOWED_TYPES:
            validated[note_index] = ValidatedDirective(directive_type="no_op")
            continue

        hours = _validate_hours(adjustment.get("hours") if isinstance(adjustment, dict) else None, battery_capacity)
        if hours is None:
            validated[note_index] = ValidatedDirective(directive_type="no_op")
            continue

        if directive_type == "solar_reduction":
            factor = adjustment.get("factor")
            if not isinstance(factor, (int, float)) or factor < 0 or factor > 1:
                validated[note_index] = ValidatedDirective(directive_type="no_op")
                continue
            validated[note_index] = ValidatedDirective(
                directive_type="solar_reduction",
                hours=hours,
                factor=float(factor),
            )

        elif directive_type == "minimum_battery_reserve":
            min_energy = adjustment.get("minimum_energy_kwh")
            if not isinstance(min_energy, (int, float)) or min_energy < 0 or min_energy > battery_capacity:
                validated[note_index] = ValidatedDirective(directive_type="no_op")
                continue
            validated[note_index] = ValidatedDirective(
                directive_type="minimum_battery_reserve",
                hours=hours,
                minimum_energy_kwh=float(min_energy),
            )

        elif directive_type == "no_charge_window":
            validated[note_index] = ValidatedDirective(
                directive_type="no_charge_window",
                hours=hours,
            )

        elif directive_type == "no_discharge_window":
            validated[note_index] = ValidatedDirective(
                directive_type="no_discharge_window",
                hours=hours,
            )

        elif directive_type == "max_grid_window":
            max_grid = adjustment.get("max_grid_kwh")
            if not isinstance(max_grid, (int, float)) or max_grid < 0 or max_grid != max_grid:
                validated[note_index] = ValidatedDirective(directive_type="no_op")
                continue
            validated[note_index] = ValidatedDirective(
                directive_type="max_grid_window",
                hours=hours,
                max_grid_kwh=float(max_grid),
            )

    # Fill any missing notes with no_op
    for i in range(num_notes):
        if validated[i] is None:
            validated[i] = ValidatedDirective(directive_type="no_op")

    return validated
