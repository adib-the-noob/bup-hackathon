from src.guardrails import ValidatedDirective, validate_directives


def test_valid_solar_reduction():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
            "explanation": "Solar cleaning",
        }
    ]
    result = validate_directives(raw, num_notes=1, battery_capacity=200)
    assert len(result) == 1
    assert result[0].directive_type == "solar_reduction"
    assert result[0].hours == [12, 13]
    assert result[0].factor == 0.25


def test_valid_no_op():
    raw = [
        {
            "note_index": 0,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Irrelevant",
        }
    ]
    result = validate_directives(raw, num_notes=1, battery_capacity=200)
    assert result[0].directive_type == "no_op"


def test_invalid_hours_duplicate():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [12, 12], "factor": 0.5},
        }
    ]
    result = validate_directives(raw, num_notes=1, battery_capacity=200)
    assert result[0].directive_type == "no_op"


def test_invalid_hours_out_of_range():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [25]},
        }
    ]
    result = validate_directives(raw, num_notes=1, battery_capacity=200)
    assert result[0].directive_type == "no_op"


def test_invalid_factor_above_one():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [10], "factor": 1.5},
        }
    ]
    result = validate_directives(raw, num_notes=1, battery_capacity=200)
    assert result[0].directive_type == "no_op"


def test_unknown_directive_type():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "fly_to_moon",
            "structured_adjustment": {"hours": [1]},
        }
    ]
    result = validate_directives(raw, num_notes=1, battery_capacity=200)
    assert result[0].directive_type == "no_op"


def test_missing_note_becomes_no_op():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_op",
            "structured_adjustment": None,
        }
    ]
    result = validate_directives(raw, num_notes=2, battery_capacity=200)
    assert len(result) == 2
    assert result[1].directive_type == "no_op"


def test_battery_reserve_exceeds_capacity():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": [18], "minimum_energy_kwh": 300},
        }
    ]
    result = validate_directives(raw, num_notes=1, battery_capacity=200)
    assert result[0].directive_type == "no_op"


def test_hours_auto_sorted():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [14, 12, 13]},
        }
    ]
    result = validate_directives(raw, num_notes=1, battery_capacity=200)
    assert result[0].hours == [12, 13, 14]


def test_multiple_notes():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [10, 11], "factor": 0.5},
        },
        {
            "note_index": 1,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
        },
        {
            "note_index": 2,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [14, 15]},
        },
    ]
    result = validate_directives(raw, num_notes=3, battery_capacity=200)
    assert len(result) == 3
    assert result[0].directive_type == "solar_reduction"
    assert result[1].directive_type == "no_op"
    assert result[2].directive_type == "no_charge_window"
