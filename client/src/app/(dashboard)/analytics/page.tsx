"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchWithAuth } from "@/lib/api";
import {
  Activity, AlertTriangle, Brain, CheckCircle, ChevronDown,
  Database, Download, Gauge, RefreshCw, Shield, XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

// ── Types ──────────────────────────────────────────────────────────────────────
interface ExperimentTrial {
  id: number;
  scenario: string;
  phase: string;
  trial_index: number;
  result: "PASS" | "FAIL" | "PARTIAL";
  observer: string;
  notes?: string;
  reaction_latency_ms?: number;
  stop_distance_m?: number;
  intent_accuracy?: number;
  ai_fps_avg?: number;
  success_rate?: number;
  success_count?: number;
  total_count?: number;
  detector_latency_avg_ms?: number;
  detector_latency_p95_ms?: number;
  detector_rate?: number;
  detector_fp_rate?: number;
  tracker_id_switch_rate?: number;
  tracker_loss_rate?: number;
  intent_ece?: number;
  intent_uncertain_rate?: number;
  intent_latency_avg_ms?: number;
  intent_latency_p95_ms?: number;
  dataset_total_samples?: number;
  dataset_min_class_count?: number;
  dataset_duplicate_rate?: number;
  dataset_corrupt_rate?: number;
  dataset_pending_review_rate?: number;
  created_at: string;
}

interface ExperimentList { total: number; items: ExperimentTrial[]; }

interface Snapshot {
  id: number;
  connected: boolean;
  navigation_mode?: string | null;
  speed?: number | null;
  ai_fps?: number | null;
  ai_persons?: number | null;
  created_at: string;
}

interface AnalyticsSummary {
  collector: { running: boolean; interval_sec: number; retention_hours: number };
  current: Snapshot | null;
  window: {
    hours: number; samples: number;
    avg_speed?: number | null; max_speed?: number | null;
    avg_ai_fps?: number | null;
    person_observations: number; obstacle_observations: number;
    navigation_modes: Record<string, number>;
  };
  logs: {
    by_severity: Record<string, number>;
    recent_alerts: Array<{
      id: number; severity: string; source: string;
      event_type: string; message: string; created_at: string;
    }>;
  };
}

function fmt(v: number | null | undefined, d = 1, s = "") {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Number(v).toFixed(d)}${s}`;
}

// ── CSV Download helper ────────────────────────────────────────────────────────
function useCSVDownload() {
  return useCallback(async (endpoint: string, filename: string) => {
    try {
      const res = await fetchWithAuth(endpoint);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert(`Download failed: ${filename}`);
    }
  }, []);
}

function DownloadBtn({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-blue-600 hover:bg-blue-50 px-2 py-1 rounded-lg transition-colors border border-slate-200 hover:border-blue-200"
    >
      <Download className="w-3 h-3" />
      {label}
    </button>
  );
}

function SkeletonLine({ w = "100%" }: { w?: string }) {
  return <div className="h-3 rounded bg-slate-100 animate-pulse" style={{ width: w }} />;
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-2 border border-dashed border-slate-200 rounded-xl text-slate-400">
      <Activity className="w-6 h-6 opacity-40" />
      <p className="text-xs text-center px-4">{label}</p>
    </div>
  );
}

function SectionHeader({ icon: Icon, title, subtitle, accent, onDownload, downloadLabel }: {
  icon: React.ElementType; title: string; subtitle: string; accent: string;
  onDownload?: () => void; downloadLabel?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 mb-5">
      <div className="flex items-center gap-3">
        <div className={`p-2.5 rounded-xl ${accent}`}>
          <Icon className="w-5 h-5 text-white" />
        </div>
        <div>
          <h3 className="text-base font-bold text-slate-800 leading-tight">{title}</h3>
          <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>
        </div>
      </div>
      {onDownload && downloadLabel && (
        <DownloadBtn onClick={onDownload} label={downloadLabel} />
      )}
    </div>
  );
}

function StatRow({ label, value, badge, badgeOk, loading }: {
  label: string; value?: string; badge?: string; badgeOk?: boolean; loading: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-slate-100 last:border-0">
      <span className="text-sm text-slate-500">{label}</span>
      <div className="flex items-center gap-2">
        {loading ? <SkeletonLine w="80px" /> : (
          <>
            <span className="text-sm font-semibold text-slate-900">{value ?? "—"}</span>
            {badge && (
              <span className={`text-xs font-medium px-1.5 py-0.5 rounded-md ${
                badgeOk === true ? "bg-emerald-100 text-emerald-700"
                  : badgeOk === false ? "bg-rose-100 text-rose-700"
                  : "bg-amber-50 text-amber-600"}`}>
                {badge}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Experiment Panel ──────────────────────────────────────────────────────────
const SCENARIO_LABELS: Record<string, string> = {
  detector_eval: "Detector Eval",
  tracker_eval: "Tracker Eval",
  intent_eval: "Intent CNN Eval",
  risk_scorer_eval: "Risk Scorer Eval",
  dataset_gate: "Dataset Gate",
  corridor_empty: "Corridor Trống",
  static_person: "Người Đứng Gần",
  approaching_person: "Người Tiến Lại",
  crossing_person: "Người Cắt Ngang",
  bad_depth: "Depth Xấu",
  perception_degrade: "Perception Degrade",
};

function ResultBadge({ result }: { result: string }) {
  const cfg = {
    PASS: { cls: "bg-emerald-100 text-emerald-700", icon: CheckCircle },
    FAIL: { cls: "bg-rose-100 text-rose-700", icon: XCircle },
    PARTIAL: { cls: "bg-amber-50 text-amber-600", icon: ChevronDown },
  }[result] ?? { cls: "bg-slate-100 text-slate-500", icon: Activity };
  const Icon = cfg.icon;
  return (
    <span className={`flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${cfg.cls}`}>
      <Icon className="w-3 h-3" /> {result}
    </span>
  );
}

function ExperimentPanel({ trials, total, loading, download }: { 
  trials: ExperimentTrial[]; total: number; loading: boolean; 
  download: (ep: string, fn: string) => Promise<void> 
}) {
  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-indigo-500">
            <Activity className="w-5 h-5 text-white" />
          </div>
          <div>
            <h3 className="text-base font-bold text-slate-800">Kết quả Thực nghiệm (Offline & Online)</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              {total} trial{total !== 1 ? "s" : ""} recorded · Offline + Online
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <DownloadBtn onClick={() => void download("/api/experiments/export/offline", "offline_eval.csv")} label="Offline CSV" />
          <DownloadBtn onClick={() => void download("/api/experiments/export/online", "online_eval.csv")} label="Online CSV" />
          <DownloadBtn onClick={() => void download("/api/experiments/export/summary", "experiment_summary.csv")} label="Summary CSV" />
          <DownloadBtn onClick={() => void download("/api/experiments/export/full", "experiment_results_full.csv")} label="Full CSV" />
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">{[0,1,2].map(i => (
          <div key={i} className="h-12 rounded-lg bg-slate-50 animate-pulse" />
        ))}</div>
      ) : trials.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center">
          <Activity className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-sm text-slate-400">Chưa có trial nào — dùng POST /api/experiments/trials để ghi số liệu</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100">
                {["#", "Scenario", "Phase", "Trial", "Result", "Latency", "Stop Dist", "FPS", "Time"].map(h => (
                  <th key={h} className="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider py-2 pr-4 last:pr-0">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {trials.map(t => (
                <tr key={t.id} className="hover:bg-slate-50 transition-colors">
                  <td className="py-2.5 pr-4 text-slate-400 font-mono text-xs">{t.id}</td>
                  <td className="py-2.5 pr-4 font-medium text-slate-800">{SCENARIO_LABELS[t.scenario] ?? t.scenario}</td>
                  <td className="py-2.5 pr-4">
                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                      t.phase === "offline" ? "bg-blue-50 text-blue-600" : "bg-teal-50 text-teal-600"
                    }`}>{t.phase}</span>
                  </td>
                  <td className="py-2.5 pr-4 text-slate-500">{t.trial_index}</td>
                  <td className="py-2.5 pr-4"><ResultBadge result={t.result} /></td>
                  <td className="py-2.5 pr-4 text-slate-600 font-mono text-xs">{fmt(t.reaction_latency_ms, 0, "ms")}</td>
                  <td className="py-2.5 pr-4 text-slate-600 font-mono text-xs">{fmt(t.stop_distance_m, 2, "m")}</td>
                  <td className="py-2.5 pr-4 text-slate-600 font-mono text-xs">{fmt(t.ai_fps_avg, 1, " fps")}</td>
                  <td className="py-2.5 text-slate-400 text-xs">{new Date(t.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── 6.2.1 Control ──────────────────────────────────────────────────────────────
function ControlSection({ summary, series, trials, loading, onDownload }: {
  summary: AnalyticsSummary | null; series: Snapshot[]; trials: ExperimentTrial[]; loading: boolean;
  onDownload: (ep: string, fn: string) => Promise<void>;
}) {
  const w = summary?.window;
  const chartData = useMemo(() =>
    series.map((s) => ({
      t: new Date(s.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      speed: s.speed ?? null,
    })), [series]);

  const dominantMode = w
    ? Object.entries(w.navigation_modes ?? {}).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "—"
    : "—";

  const tStop = trials.find(t => t.stop_distance_m != null);
  const stopDist = tStop ? `${tStop.stop_distance_m} m` : "— pending trial";
  const badgeStop = tStop ? "trial data" : "pending trial";

  const tNav = trials.filter(t => t.success_count != null && t.total_count != null);
  let navGoal = "— pending trial";
  let badgeNav = "pending trial";
  if (tNav.length > 0) {
    const sumS = tNav.reduce((acc, t) => acc + (t.success_count || 0), 0);
    const sumT = tNav.reduce((acc, t) => acc + (t.total_count || 0), 0);
    navGoal = `${((sumS / sumT) * 100).toFixed(1)}%`;
    badgeNav = "trial data";
  }

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
      <SectionHeader icon={Gauge} title="Điều khiển và Chuyển động"
        subtitle="velocity error · serial stability · odometry · stop distance · Nav2 goal"
        accent="bg-blue-500"
        onDownload={() => void onDownload("/api/experiments/export/offline", "offline_eval.csv")}
        downloadLabel="Offline CSV" />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        <div className="space-y-0">
          <StatRow label="Sai số vận tốc (avg speed)" value={fmt(w?.avg_speed, 3, " m/s")}
            badge={fmt(w?.max_speed, 2, " m/s max")} loading={loading} />
          <StatRow label="Độ ổn định serial" value="— pending log" badge="pending trial" loading={loading} />
          <StatRow label="Sai số odometry" value="— pending log" badge="pending trial" loading={loading} />
          <StatRow label="Khoảng cách stop thực tế" value={stopDist} badge={badgeStop} loading={loading} />
          <StatRow label="Navigation mode" value={dominantMode} loading={loading} />
          <StatRow label="Tỷ lệ đến Goal Nav2" value={navGoal} badge={badgeNav} loading={loading} />
          {!loading && w && (
            <p className="pt-3 text-xs text-slate-400">{w.samples} snapshots · cửa sổ {w.hours}h</p>
          )}
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400 mb-3">Tốc độ robot theo thời gian</p>
          <div className="h-[220px]">
            {loading ? <div className="h-full bg-slate-50 rounded-xl animate-pulse" />
              : chartData.length === 0 ? <EmptyChart label="Chưa có snapshot vận tốc từ collector" />
              : (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="t" fontSize={10} stroke="#94a3b8" tickLine={false} />
                    <YAxis fontSize={10} stroke="#94a3b8" tickLine={false} width={38} tickFormatter={(v) => v.toFixed(2)} />
                    <Tooltip formatter={(v: unknown) => [`${Number(v).toFixed(3)} m/s`, "Speed"]} />
                    <Line type="monotone" dataKey="speed" name="Speed" stroke="#3b82f6" strokeWidth={2} dot={false} connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 6.2.2 Perception ───────────────────────────────────────────────────────────
function PerceptionSection({ summary, series, trials, loading, onDownload }: {
  summary: AnalyticsSummary | null; series: Snapshot[]; trials: ExperimentTrial[]; loading: boolean;
  onDownload: (ep: string, fn: string) => Promise<void>;
}) {
  const w = summary?.window;
  const fpsData = useMemo(() =>
    series.map((s) => ({
      t: new Date(s.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      fps: s.ai_fps ?? null,
    })), [series]);

  const tDet = trials.find(t => t.scenario === "detector_eval");
  const tTrk = trials.find(t => t.scenario === "tracker_eval");
  const tInt = trials.find(t => t.scenario === "intent_eval");

  const valLatDet = tDet ? `${tDet.detector_latency_avg_ms}ms / ${tDet.detector_latency_p95_ms}ms` : "— pending profiler";
  const valTrack = tTrk ? `sw: ${tTrk.tracker_id_switch_rate} | loss: ${tTrk.tracker_loss_rate}` : "— pending tracker log";
  const valLatInt = tInt ? `${tInt.intent_latency_avg_ms}ms / ${tInt.intent_latency_p95_ms}ms` : "— pending profiler";
  const valAccInt = tInt ? `${(tInt.intent_accuracy ?? 0) * 100}%` : "— pending eval";
  const valEceInt = tInt ? `${tInt.intent_ece}` : "— pending eval";
  const valUncInt = tInt ? `${((tInt.intent_uncertain_rate ?? 0) * 100).toFixed(1)}%` : "— pending runtime log";

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
      <SectionHeader icon={Brain} title="Perception và AI"
        subtitle="YOLO latency · ID switch · Temporal Intent CNN · accuracy 5 cls · ECE · UNCERTAIN · throughput"
        accent="bg-violet-500"
        onDownload={() => void onDownload("/api/experiments/export/offline", "offline_eval.csv")}
        downloadLabel="Offline CSV" />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        <div className="space-y-0">
          <StatRow label="Latency YOLO (avg / p95)" value={valLatDet} badge={tDet ? "trial data" : "pending trial"} loading={loading} />
          <StatRow label="ID switch / track loss" value={valTrack} badge={tTrk ? "trial data" : "pending trial"} loading={loading} />
          <StatRow label="Latency Temporal Intent CNN" value={valLatInt} badge={tInt ? "trial data" : "pending trial"} loading={loading} />
          <StatRow label="Accuracy 5 lớp trainable" value={valAccInt} badge={tInt ? "trial data" : "pending eval"} loading={loading} />
          <StatRow label="ECE và calibration" value={valEceInt} badge={tInt ? "trial data" : "pending eval"} loading={loading} />
          <StatRow label="Tỷ lệ UNCERTAIN" value={valUncInt} badge={tInt ? "trial data" : "pending trial"} loading={loading} />
          <StatRow label="AI FPS trung bình" value={fmt(w?.avg_ai_fps, 1, " FPS")}
            badge={w?.avg_ai_fps != null ? (w.avg_ai_fps >= 20 ? "realtime ✓" : "< 20 FPS") : "pending"}
            badgeOk={w?.avg_ai_fps != null ? w.avg_ai_fps >= 20 : undefined}
            loading={loading} />
          <StatRow label="Person observations (24h)" value={String(w?.person_observations ?? "—")} loading={loading} />
          <StatRow label="Throughput theo số người" value="— pending scenario" badge="pending trial" loading={loading} />
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400 mb-3">AI FPS theo thời gian</p>
          <div className="h-[220px]">
            {loading ? <div className="h-full bg-slate-50 rounded-xl animate-pulse" />
              : fpsData.length === 0 ? <EmptyChart label="Chưa có AI FPS snapshot từ collector" />
              : (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={fpsData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="t" fontSize={10} stroke="#94a3b8" tickLine={false} />
                    <YAxis fontSize={10} stroke="#94a3b8" tickLine={false} width={38} />
                    <Tooltip formatter={(v: unknown) => [`${Number(v).toFixed(1)} FPS`]} />
                    <Line type="monotone" dataKey="fps" name="AI FPS" stroke="#7c3aed" strokeWidth={2} dot={false} connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 6.2.3 Dataset ──────────────────────────────────────────────────────────────
function DatasetSection({ trials, loading, onDownload }: { 
  trials: ExperimentTrial[]; loading: boolean; 
  onDownload: (ep: string, fn: string) => Promise<void> 
}) {
  const tDat = trials.find(t => t.scenario === "dataset_gate");
  const getVal = (v: number | null | undefined, suffix = "") => tDat && v != null ? `${v}${suffix}` : "— pending data";
  const rows = [
    { label: "Tổng số ROI", value: getVal(tDat?.dataset_total_samples) },
    { label: "Số track hợp lệ", value: getVal(tDat?.dataset_min_class_count) },
    { label: "Phân phối lớp (5 class)", value: tDat ? "Balanced" : "— pending data" },
    { label: "Duplicate", value: getVal(tDat?.dataset_duplicate_rate, "%") },
    { label: "Corrupt", value: getVal(tDat?.dataset_corrupt_rate, "%") },
    { label: "Pending review", value: getVal(tDat?.dataset_pending_review_rate, "%") },
    { label: "Số sample trainable", value: getVal(tDat?.dataset_total_samples) },
  ];
  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
      <SectionHeader icon={Database} title="Dataset"
        subtitle="ROI · track hợp lệ · phân phối lớp · duplicate / corrupt · pending review · trainable"
        accent="bg-emerald-500"
        onDownload={() => void onDownload("/api/experiments/export/offline", "offline_eval.csv")}
        downloadLabel="Dataset CSV" />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        <div className="space-y-0">
          {rows.map((r) => (
            <StatRow key={r.label} label={r.label} value={r.value} badge={tDat ? "trial data" : "pending pipeline"} loading={loading} />
          ))}
          <p className="pt-3 text-xs text-slate-400">
            Sẽ được điền sau khi chạy auto-label pipeline và expose{" "}
            <code className="bg-slate-100 px-1 rounded">/api/dataset/stats</code>.
          </p>
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400 mb-3">Phân phối lớp</p>
          <div className="h-[220px]">
            <EmptyChart label="Chờ /api/dataset/stats — chạy auto-label pipeline trước" />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 6.2.4 Safety ──────────────────────────────────────────────────────────────
const SAFETY_SCENARIOS = [
  { id: "approach", label: "Người tiến lại gần", trigger: "dist < 0.5m", expected: "STOP + REPULSE < 100ms" },
  { id: "cross",    label: "Người cắt ngang",    trigger: "crossing path", expected: "SLOW + STEER < 200ms" },
  { id: "depth",    label: "Depth xấu",           trigger: "depth variance", expected: "HOLD + ALERT" },
  { id: "stale",    label: "Robot state stale",   trigger: "telemetry > 2s", expected: "ESTOP immediately" },
  { id: "ai_slow",  label: "AI chậm / stale",     trigger: "latency > 500ms", expected: "DEGRADE → LIDAR-only" },
] as const;

function SafetySection({ summary, loading, onDownload }: {
  summary: AnalyticsSummary | null; loading: boolean;
  onDownload: (ep: string, fn: string) => Promise<void>;
}) {
  const alerts = summary?.logs.recent_alerts ?? [];
  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
      <SectionHeader icon={Shield} title="Safety và Degrade"
        subtitle="phản ứng theo scenario · latency · success rate · recent alerts"
        accent="bg-rose-500"
        onDownload={() => void onDownload("/api/experiments/export/online", "online_eval.csv")}
        downloadLabel="Online CSV" />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400 mb-3">Kịch bản đánh giá (online)</p>
          <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 overflow-hidden">
            {SAFETY_SCENARIOS.map((s) => (
              <div key={s.id} className="px-4 py-3 hover:bg-slate-50 transition-colors">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-800">{s.label}</span>
                  <span className="text-xs font-mono text-slate-400">{s.trigger}</span>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-xs text-slate-500">{s.expected}</span>
                  <span className="text-xs px-1.5 py-0.5 rounded-md bg-amber-50 text-amber-600 font-medium">pending trial</span>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Recent alerts (live)</p>
          </div>
          <div className="space-y-2 max-h-[280px] overflow-y-auto">
            {loading ? (
              [0, 1, 2].map((i) => (
                <div key={i} className="rounded-lg border border-slate-100 p-3 space-y-2">
                  <SkeletonLine w="60%" /><SkeletonLine w="90%" />
                </div>
              ))
            ) : alerts.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-slate-400 text-sm">
                Không có cảnh báo trong cửa sổ 24h
              </div>
            ) : (
              alerts.map((a) => (
                <div key={a.id} className="rounded-lg border border-slate-100 p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <StatusBadge status={a.severity === "WARNING" ? "warning" : "error"}>{a.severity}</StatusBadge>
                    <span className="font-medium text-slate-700">{a.source}</span>
                    <span className="text-slate-400 text-xs ml-auto">{new Date(a.created_at).toLocaleTimeString()}</span>
                  </div>
                  <p className="text-slate-600">{a.message}</p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function AnalyticsPage() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [series, setSeries] = useState<Snapshot[]>([]);
  const [trials, setTrials] = useState<ExperimentTrial[]>([]);
  const [totalTrials, setTotalTrials] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const download = useCSVDownload();

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const [sumRes, serRes, trialRes] = await Promise.all([
        fetchWithAuth("/api/analytics/summary?hours=24"),
        fetchWithAuth("/api/analytics/timeseries?hours=6&limit=240"),
        fetchWithAuth("/api/experiments/trials?limit=100")
      ]);
      setSummary((await sumRes.json()) as AnalyticsSummary);
      setSeries((await serRes.json()) as Snapshot[]);
      const trialData = await trialRes.json() as ExperimentList;
      setTrials(trialData.items || []);
      setTotalTrials(trialData.total || 0);
      setLastUpdated(new Date());
    } catch { /* keep stale */ } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const run = async () => { await load(); };
    void run();
    const iv = setInterval(() => { void run(); }, 10_000);
    return () => clearInterval(iv);
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Analytics Dashboard</h2>
          <p className="text-sm text-slate-500 mt-1">
            Chỉ số thực nghiệm · Điều khiển · Perception · Dataset · Safety
          </p>
        </div>
        <div className="flex items-center gap-3">
          <DownloadBtn
            onClick={() => void download("/api/experiments/export/full", "experiment_results_full.csv")}
            label="Export All CSV"
          />
          <StatusBadge status={summary?.collector.running ? "success" : "warning"}>
            {summary?.collector.running ? "collector live" : "collector offline"}
          </StatusBadge>
          <button onClick={() => void load(true)} disabled={refreshing} aria-label="Refresh"
            className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800 transition-colors disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
            {lastUpdated ? lastUpdated.toLocaleTimeString() : "—"}
          </button>
        </div>
      </div>
      <ControlSection summary={summary} series={series} trials={trials} loading={loading} onDownload={download} />
      <PerceptionSection summary={summary} series={series} trials={trials} loading={loading} onDownload={download} />
      <DatasetSection trials={trials} loading={loading} onDownload={download} />
      <SafetySection summary={summary} loading={loading} onDownload={download} />
      <ExperimentPanel trials={trials} total={totalTrials} loading={loading} download={download} />
    </div>
  );
}
