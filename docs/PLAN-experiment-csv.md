# PLAN: Experiment CSV Export + Experiment Guide
**Date:** 2026-05-05
**Version target:** v1.5.0
**Branch:** feature/experiment-csv-export

---

## Scope

Hai deliverable song song:

### A. Backend — Experiment Trial API + CSV Export
Cho phép ghi số liệu từng trial thực nghiệm vào DB và xuất CSV.

### B. Frontend — Analytics page thêm nút Download CSV
Thêm Download buttons vào từng section của trang Analytics.

### C. Documentation — Hướng dẫn thực nghiệm
File markdown đầy đủ hướng dẫn chạy 11 thực nghiệm (5 offline + 6 online).

---

## Files cần tạo / sửa

### Backend (rai_website/server/)
| File | Action | Mô tả |
|------|--------|-------|
| `app/models/experiment_trial.py` | CREATE | Model DB cho trial result |
| `app/schemas/experiment.py` | CREATE | Pydantic schemas |
| `app/services/experiment_service.py` | CREATE | CRUD + CSV generation |
| `app/routers/experiments.py` | CREATE | REST endpoints |
| `app/main.py` | MODIFY | Register experiments router |
| `alembic/versions/XXXX_add_experiment_trials.py` | CREATE | Migration |

### Frontend (rai_website/client/)
| File | Action | Mô tả |
|------|--------|-------|
| `src/app/(dashboard)/analytics/page.tsx` | MODIFY | Thêm CSV download buttons |

### Documentation
| File | Action | Mô tả |
|------|--------|-------|
| `d:/nckh/paper/huong_dan_thuc_nghiem.md` | CREATE | Hướng dẫn đầy đủ 11 thực nghiệm |

---

## API Design

### Endpoints

```
POST   /api/experiments/trials          — Ghi 1 trial result
GET    /api/experiments/trials          — List trials (filter by scenario, date)
GET    /api/experiments/trials/{id}     — Chi tiết 1 trial
DELETE /api/experiments/trials/{id}    — Xóa trial (operator only)

GET    /api/experiments/export/offline  — CSV cho 5 offline evaluations
GET    /api/experiments/export/online   — CSV cho 6 online scenarios
GET    /api/experiments/export/full     — Full CSV tất cả trials
GET    /api/experiments/export/summary  — CSV summary (aggregated by scenario)
```

### ExperimentTrial Schema

```python
class ExperimentTrial(Base):
    id: int (PK)
    scenario: str           # "detector_eval", "tracker_eval", "intent_eval",
                            # "risk_scorer_eval", "dataset_gate",
                            # "corridor_empty", "static_person",
                            # "approaching_person", "crossing_person",
                            # "bad_depth", "perception_degrade"
    phase: str              # "offline" | "online"
    trial_index: int        # 1..N (lần chạy thứ mấy)
    result: str             # "PASS" | "FAIL" | "PARTIAL"
    observer: str           # Tên người quan sát
    notes: str | None

    # Offline 6.3.1.1 — Detector
    detector_latency_avg_ms: float | None
    detector_latency_p95_ms: float | None
    detector_rate: float | None        # %
    detector_fp_rate: float | None     # %

    # Offline 6.3.1.2 — Tracker
    tracker_id_switch_rate: float | None
    tracker_loss_rate: float | None
    tracker_lifespan_avg: float | None
    tracker_fragment_rate: float | None

    # Offline 6.3.1.3 — Intent CNN
    intent_accuracy: float | None      # top-1 acc
    intent_f1_stationary: float | None
    intent_f1_approaching: float | None
    intent_f1_departing: float | None
    intent_f1_crossing: float | None
    intent_f1_erratic: float | None
    intent_ece: float | None
    intent_uncertain_rate: float | None
    intent_latency_avg_ms: float | None
    intent_latency_p95_ms: float | None

    # Offline 6.3.1.4 — Risk Scorer
    risk_mean_approaching: float | None
    risk_mean_stationary: float | None
    risk_auc: float | None
    risk_top_features: str | None      # JSON string

    # Offline 6.3.1.5 — Dataset Gate
    dataset_total_samples: int | None
    dataset_min_class_count: int | None
    dataset_duplicate_rate: float | None
    dataset_corrupt_rate: float | None
    dataset_pending_review_rate: float | None
    dataset_manifest_ready: bool | None

    # Online common
    ai_fps_avg: float | None
    uncertain_count: int | None
    reaction_latency_ms: float | None
    stop_distance_m: float | None
    success_count: int | None
    total_count: int | None
    success_rate: float | None         # computed

    # Online specific — Corridor Empty
    travel_time_s: float | None
    false_stop_count: int | None

    # Online — Robot behavior
    robot_behavior: str | None         # STOP/DETOUR/WAIT/SLOW/STEER/HOLD/ALERT

    # Timestamps
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime (server default)
```

---

## CSV Columns Per Export Type

### offline_eval.csv
```
scenario, trial_index, result, observer,
detector_latency_avg_ms, detector_latency_p95_ms, detector_rate, detector_fp_rate,
tracker_id_switch_rate, tracker_loss_rate, tracker_lifespan_avg, tracker_fragment_rate,
intent_accuracy, intent_f1_stationary, intent_f1_approaching, intent_f1_departing,
intent_f1_crossing, intent_f1_erratic, intent_ece, intent_uncertain_rate,
intent_latency_avg_ms, intent_latency_p95_ms,
risk_mean_approaching, risk_mean_stationary, risk_auc, risk_top_features,
dataset_total_samples, dataset_min_class_count, dataset_duplicate_rate,
dataset_corrupt_rate, dataset_pending_review_rate, dataset_manifest_ready,
notes, started_at, ended_at
```

### online_eval.csv
```
scenario, trial_index, result, observer,
ai_fps_avg, uncertain_count, reaction_latency_ms,
stop_distance_m, robot_behavior, success_count, total_count, success_rate,
travel_time_s, false_stop_count,
notes, started_at, ended_at
```

### summary_eval.csv (aggregated)
```
scenario, phase, n_trials, n_pass, n_fail, pass_rate,
mean_reaction_latency_ms, std_reaction_latency_ms,
mean_stop_distance_m, std_stop_distance_m,
mean_success_rate, mean_ai_fps_avg
```

---

## Frontend Changes

Thêm vào `analytics/page.tsx`:
- Header: nút "Export Full CSV" → `GET /api/experiments/export/full`
- Mỗi section (6.2.1, 6.2.2, 6.2.3, 6.2.4): nút nhỏ "↓ CSV" tương ứng
- Thêm panel "📋 Experiment Trials" hiển thị list trials gần nhất với kết quả PASS/FAIL

---

## Task Breakdown

### T1 — DB Model + Migration (backend-specialist)
- Tạo `ExperimentTrial` model
- Tạo Alembic migration
- Tạo Pydantic schemas

### T2 — Service + Router (backend-specialist)
- `experiment_service.py`: CRUD + CSV generation (io.StringIO + csv module)
- `experiments.py` router: all endpoints
- Register router in `main.py`

### T3 — Frontend Download UI (frontend-specialist)
- Thêm ExperimentPanel component
- Thêm download buttons trong analytics page

### T4 — Documentation (documentation-writer)
- `huong_dan_thuc_nghiem.md` với đầy đủ step-by-step

---

## Acceptance Criteria

- [ ] `POST /api/experiments/trials` returns 201 với trial object
- [ ] `GET /api/experiments/export/offline` trả về CSV đúng format, download được
- [ ] `GET /api/experiments/export/online` trả về CSV đúng format
- [ ] `GET /api/experiments/export/summary` trả về aggregated CSV
- [ ] Frontend: nút Download hiển thị và trigger download
- [ ] `huong_dan_thuc_nghiem.md` cover đủ 11 scenarios
