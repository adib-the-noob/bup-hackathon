import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from src.llm_interpreter import interpret_notes
from src.models import HealthResponse, OptimizeRequest, OptimizeResponse
from src.optimizer import solve

load_dotenv()

app = FastAPI(title="GridWise LLM Energy Optimizer")


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeResponse)
async def optimize_energy(request: OptimizeRequest):
    try:
        interpretation, optimizer_directives = interpret_notes(
            request.operator_notes,
            request.hours,
            request.battery,
        )

        plan, total_grid, total_cost, peak_grid, summary = solve(
            request.hours,
            request.battery,
            optimizer_directives,
        )

        return OptimizeResponse(
            scenario_id=request.scenario_id,
            directive_interpretation=interpretation,
            hourly_plan=plan,
            total_grid_kwh=round(total_grid, 4),
            total_cost_bdt=round(total_cost, 4),
            peak_grid_kwh=round(peak_grid, 4),
            plan_summary=summary,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}")
