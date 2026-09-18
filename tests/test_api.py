import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from src.guardrails import ValidatedDirective


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def _sample_request():
    hours = []
    for h in range(24):
        demand = 100 + (50 if 8 <= h <= 20 else 0)
        solar = max(0, 80 - abs(h - 12) * 15)
        tariff = 5 + (15 if 17 <= h <= 21 else 0)
        hours.append({
            "hour": h,
            "demand_kwh": float(demand),
            "solar_kwh": float(solar),
            "tariff_bdt_per_kwh": float(tariff),
        })
    return {
        "scenario_id": "TEST-001",
        "operator_notes": ["The cafeteria menu changes tomorrow."],
        "hours": hours,
        "battery": {
            "capacity_kwh": 300.0,
            "initial_energy_kwh": 150.0,
            "minimum_energy_kwh": 30.0,
            "max_charge_kwh_per_hour": 60.0,
            "max_discharge_kwh_per_hour": 60.0,
        },
    }


def test_optimize_energy_no_op(client):
    req = _sample_request()
    with patch("main.interpret_notes") as mock_interp:
        mock_interp.return_value = (
            [
                {
                    "note_index": 0,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Does not affect schedule",
                }
            ],
            [],
        )
        resp = client.post("/optimize-energy", json=req)

    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario_id"] == "TEST-001"
    assert len(data["hourly_plan"]) == 24
    assert len(data["directive_interpretation"]) == 1
    assert data["directive_interpretation"][0]["directive_type"] == "no_op"
    assert "total_grid_kwh" in data
    assert "total_cost_bdt" in data
    assert "peak_grid_kwh" in data
    assert "plan_summary" in data


def test_optimize_energy_with_directive(client):
    req = _sample_request()
    req["operator_notes"] = ["Solar output drops to 20% from 1 PM to 3 PM."]
    with patch("main.interpret_notes") as mock_interp:
        mock_interp.return_value = (
            [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "solar_reduction",
                    "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
                    "explanation": "Solar reduced",
                }
            ],
            [
                ValidatedDirective(
                    directive_type="solar_reduction",
                    hours=[13, 14],
                    factor=0.2,
                )
            ],
        )
        resp = client.post("/optimize-energy", json=req)

    assert resp.status_code == 200
    data = resp.json()
    assert data["directive_interpretation"][0]["directive_type"] == "solar_reduction"
    assert data["hourly_plan"][13]["solar_used_kwh"] <= 80.0 * 0.2 + 0.1


def test_malformed_json(client):
    resp = client.post(
        "/optimize-energy",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code in (400, 422)


def test_missing_required_field(client):
    resp = client.post("/optimize-energy", json={"scenario_id": "x"})
    assert resp.status_code == 422
