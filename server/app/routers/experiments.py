from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from app.middleware.auth import get_current_operator, get_current_user
from app.schemas.experiment import ExperimentTrialCreate, ExperimentTrialList, ExperimentTrialRead
from app.services import experiment_service

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.post("/trials", response_model=ExperimentTrialRead, status_code=201,
             dependencies=[Depends(get_current_operator)])
async def create_trial(body: ExperimentTrialCreate):
    """Record a new experiment trial result."""
    trial = await experiment_service.create_trial(body)
    return trial


@router.get("/trials", response_model=ExperimentTrialList,
            dependencies=[Depends(get_current_user)])
async def list_trials(
    scenario: str | None = Query(default=None),
    phase: str | None = Query(default=None, pattern="^(offline|online)$"),
    result: str | None = Query(default=None, pattern="^(PASS|FAIL|PARTIAL)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List experiment trials with optional filters."""
    total, items = await experiment_service.list_trials(
        scenario=scenario, phase=phase, result=result, limit=limit, offset=offset
    )
    return {"total": total, "items": items}


@router.get("/trials/{trial_id}", response_model=ExperimentTrialRead,
            dependencies=[Depends(get_current_user)])
async def get_trial(trial_id: int):
    """Get a single trial by ID."""
    trial = await experiment_service.get_trial(trial_id)
    if trial is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    return trial


@router.delete("/trials/{trial_id}", status_code=204,
               dependencies=[Depends(get_current_operator)])
async def delete_trial(trial_id: int):
    """Delete a trial (operator only)."""
    ok = await experiment_service.delete_trial(trial_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Trial not found")
    return Response(status_code=204)


# ── CSV Export ─────────────────────────────────────────────────────────────────

def _csv_response(csv_content: str, filename: str) -> StreamingResponse:
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/offline", dependencies=[Depends(get_current_user)])
async def export_offline():
    """Download CSV for offline evaluations (§6.3.1.1–6.3.1.5)."""
    csv_data = await experiment_service.export_offline_csv()
    return _csv_response(csv_data, "offline_eval.csv")


@router.get("/export/online", dependencies=[Depends(get_current_user)])
async def export_online():
    """Download CSV for online scenario evaluations (§6.3.2.1–6.3.2.6)."""
    csv_data = await experiment_service.export_online_csv()
    return _csv_response(csv_data, "online_eval.csv")


@router.get("/export/full", dependencies=[Depends(get_current_user)])
async def export_full():
    """Download full CSV with all trials and all columns."""
    csv_data = await experiment_service.export_full_csv()
    return _csv_response(csv_data, "experiment_results_full.csv")


@router.get("/export/summary", dependencies=[Depends(get_current_user)])
async def export_summary():
    """Download aggregated summary CSV (mean ± std per scenario)."""
    csv_data = await experiment_service.export_summary_csv()
    return _csv_response(csv_data, "experiment_summary.csv")
