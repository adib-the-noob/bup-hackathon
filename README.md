# GridWise LLM — Smart Campus Energy Optimization

LLM-assisted energy scheduling API for BUP CSE Fest 2026 Hackathon.

## Architecture

```
Operator Notes → LLM Interpretation → Deterministic Guardrails → LP Optimizer → 24h Schedule
```

1. **LLM** interprets natural-language operator notes into structured directives
2. **Guardrails** deterministically validate the LLM output (safe failure on invalid data)
3. **LP Solver** (scipy linprog) computes the minimum-cost 24-hour battery schedule

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check, returns `{"status": "ok"}` |
| `/optimize-energy` | POST | Accepts scenario + notes, returns interpretation + schedule |

## Quickstart

### Prerequisites

- Python 3.13+
- OpenAI API key

### Local Setup

```bash
pip install -e .
cp .env.example .env
# Edit .env with your OPENAI_API_KEY
uvicorn main:app --reload
```

### Docker

```bash
docker compose up --build
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | — | OpenAI/OpenAI-compatible API key |
| `OPENAI_BASE_URL` | Yes | — | Base URL for the model router/provider |
| `OPENAI_MODEL` | Yes | — | Model for operator-note interpretation |

## Testing

```bash
# Validate against public sample pack (requires running server)
python -m tools.run_samples.py
```

## Example Request

```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "TEST-001",
    "operator_notes": ["Solar output drops to 20% from 1 PM to 3 PM."],
    "hours": [
      {"hour": 0, "demand_kwh": 180, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
      ...
      {"hour": 23, "demand_kwh": 200, "solar_kwh": 0, "tariff_bdt_per_kwh": 9}
    ],
    "battery": {
      "capacity_kwh": 500,
      "initial_energy_kwh": 200,
      "minimum_energy_kwh": 50,
      "max_charge_kwh_per_hour": 100,
      "max_discharge_kwh_per_hour": 100
    }
  }'
```

## Supported Directives

| Type | Effect |
|------|--------|
| `solar_reduction` | Reduces usable solar by factor for listed hours |
| `minimum_battery_reserve` | Raises minimum battery level for listed hours |
| `no_charge_window` | Battery charging disabled for listed hours |
| `no_discharge_window` | Battery discharging disabled for listed hours |
| `max_grid_window` | Grid import capped for listed hours |
| `no_op` | No effect on schedule |

## Dependencies

- FastAPI + uvicorn (HTTP server)
- Pydantic (data validation)
- scipy (LP solver)
- OpenAI SDK (LLM interpretation)
- python-dotenv (config)
