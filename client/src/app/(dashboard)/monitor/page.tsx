"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { useWebSocket } from "@/hooks/useWebSocket";
import { fetchWithAuth } from "@/lib/api";
import {
  Activity,
  Battery,
  BatteryCharging,
  Cpu,
  Database,
  Gauge,
  MapPin,
  Navigation,
  Play,
  Radio,
  Save,
  Square,
  Timer,
  UserRound,
  VideoOff,
  Zap,
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TrackedEntity {
  track_id: number;
  class_name: string;
  confidence: number;
  distance?: number;
  distance_source?: string;
  intent_name?: string;
  intent_confidence?: number;
  position_xyz_m?: number[];
  velocity_xyz_mps?: number[];
  heading_rad?: number;
  bbox_xywh?: number[];
}

interface DetectionPayload {
  frame_id?: number;
  sequence?: number;
  mode?: string;
  inference_ms?: number;
  fps?: number;
  connected?: boolean;
  source_id?: string;
  timestamp_us?: number;
  received_at?: number;
  persons?: TrackedEntity[];
  obstacles?: TrackedEntity[];
  entities?: TrackedEntity[];
  metrics?: {
    fps?: number;
    inference_ms?: number;
    total_latency_ms?: number;
    camera_latency_ms?: number;
    detector_latency_ms?: number;
    fusion_latency_ms?: number;
  };
  persons_count?: number;
  obstacles_count?: number;
}

interface WheeltecTelemetry {
  connected?: boolean;
  vx?: number | null;
  vy?: number | null;
  vtheta?: number | null;
  pos_x?: number | null;
  pos_y?: number | null;
  yaw?: number | null;
  battery_percent?: number | null;
  voltage?: number | null;
  charging?: boolean;
  navigation_mode?: string | null;
  imu?: {
    roll?: number;
    pitch?: number;
    yaw?: number;
    ax?: number;
    ay?: number;
    az?: number;
  };
}

interface RobotStatus {
  robot?: WheeltecTelemetry;
  ai?: Record<string, unknown>;
}

interface AdaptiveMetrics {
  state?: string;
  ready?: boolean;
  reason?: string | null;
  fps?: number;
  inference_ms?: number;
  mode?: string;
  persons?: number;
  obstacles?: number;
  result_connected?: boolean;
  result_sequence?: number;
  adaptive_metrics?: {
    camera_latency_ms?: number;
    detector_latency_ms?: number;
    fusion_latency_ms?: number;
    total_latency_ms?: number;
  };
}

interface DatasetStatus {
  status: "idle" | "recording" | "stopped" | "discarded";
  dataset_mode?: string | null;
  session_id?: string;
  frame_count?: number;
  bytes_total?: number;
  saved?: boolean;
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function MonitorPage() {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const lastUrlRef = useRef<string | null>(null);
  const [hasFrame, setHasFrame] = useState(false);
  const [streamStatus, setStreamStatus] = useState("No frames received");
  const [detections, setDetections] = useState<DetectionPayload>({});
  const [metrics, setMetrics] = useState<AdaptiveMetrics>({});
  const [robotStatus, setRobotStatus] = useState<RobotStatus>({});
  const [dataset, setDataset] = useState<DatasetStatus>({ status: "idle" });
  const [datasetBusy, setDatasetBusy] = useState(false);
  const [datasetMessage, setDatasetMessage] = useState("");

  // ─── Video WebSocket ───────────────────────────────────────────────────────

  const { isConnected } = useWebSocket("/ws/video", {
    binaryType: "blob",
    onMessage: (msg) => {
      if (typeof msg.data === "string") {
        setStreamStatus(msg.data);
        return;
      }
      const url = URL.createObjectURL(msg.data as Blob);
      if (imgRef.current) imgRef.current.src = url;
      if (lastUrlRef.current) URL.revokeObjectURL(lastUrlRef.current);
      lastUrlRef.current = url;
      setHasFrame(true);
      setStreamStatus("Receiving frames");
    },
  });

  useEffect(() => {
    return () => {
      if (lastUrlRef.current) URL.revokeObjectURL(lastUrlRef.current);
    };
  }, []);

  // ─── Polling: detection + metrics + robot status ───────────────────────────

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const [detRes, metricsRes, statusRes] = await Promise.all([
          fetchWithAuth("/api/robot/detections"),
          fetchWithAuth("/api/robot/metrics"),
          fetchWithAuth("/api/robot/status"),
        ]);
        if (cancelled) return;
        setDetections(await detRes.json());
        setMetrics(await metricsRes.json());
        setRobotStatus(await statusRes.json());
      } catch {
        if (!cancelled) {
          setDetections({});
          setMetrics({});
          setRobotStatus({});
        }
      }
    };
    poll();
    const timer = setInterval(poll, 500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  // ─── Dataset status ────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    const loadStatus = async () => {
      try {
        const response = await fetchWithAuth("/api/datasets/collection");
        const status = await response.json();
        if (cancelled) return;
        setDataset(status);
      } catch {
        if (!cancelled) setDataset({ status: "idle" });
      }
    };
    void loadStatus();
    return () => { cancelled = true; };
  }, []);

  // ─── Dataset actions ───────────────────────────────────────────────────────

  const startCollection = async () => {
    setDatasetBusy(true);
    setDatasetMessage("");
    try {
      const response = await fetchWithAuth("/api/datasets/collection/start", {
        method: "POST",
        body: JSON.stringify({ mode: "intent_cnn" }),
      });
      setDataset(await response.json());
    } catch (error) {
      setDatasetMessage(error instanceof Error ? error.message : "Cannot start collection");
    } finally {
      setDatasetBusy(false);
    }
  };

  const stopCollection = async () => {
    setDatasetBusy(true);
    setDatasetMessage("");
    try {
      const response = await fetchWithAuth("/api/datasets/collection/stop", { method: "POST" });
      setDataset(await response.json());
    } catch (error) {
      setDatasetMessage(error instanceof Error ? error.message : "Cannot stop collection");
    } finally {
      setDatasetBusy(false);
    }
  };

  const saveCollection = async () => {
    setDatasetBusy(true);
    setDatasetMessage("");
    try {
      const response = await fetchWithAuth("/api/datasets/collection/save", { method: "POST" });
      setDataset(await response.json());
      await downloadRawCollection();
      setDatasetMessage("Raw sequence dataset downloaded. Upload that zip on Dataset to run server auto-label.");
    } catch (error) {
      setDatasetMessage(error instanceof Error ? error.message : "Cannot save dataset");
    } finally {
      setDatasetBusy(false);
    }
  };

  const downloadRawCollection = async () => {
    const response = await fetchWithAuth("/api/datasets/collection/download");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const match = disposition.match(/filename\*?=(?:UTF-8'')?\"?([^";]+)\"?/i);
    const link = document.createElement("a");
    link.href = url;
    link.download = decodeURIComponent(match?.[1] ?? "adaptive_context_aware_raw_sequences.zip");
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  // ─── Derived state ─────────────────────────────────────────────────────────

  const entities = detections.entities ?? detections.persons ?? [];
  const obstacles = detections.obstacles ?? [];
  const isRecording = dataset.status === "recording";
  const canSave = dataset.status === "stopped" && (dataset.frame_count ?? 0) > 0;
  const telemetry = robotStatus.robot ?? {};
  const adaptMetrics = detections.metrics ?? {};
  const camLatency = adaptMetrics.camera_latency_ms ?? metrics.adaptive_metrics?.camera_latency_ms;
  const detLatency = adaptMetrics.detector_latency_ms ?? metrics.adaptive_metrics?.detector_latency_ms;
  const fusionLatency = adaptMetrics.fusion_latency_ms ?? metrics.adaptive_metrics?.fusion_latency_ms;
  const totalLatency = adaptMetrics.total_latency_ms ?? adaptMetrics.inference_ms ?? metrics.inference_ms ?? detections.inference_ms;
  const fps = adaptMetrics.fps ?? detections.fps ?? metrics.fps;
  const resultSeq = detections.sequence ?? detections.frame_id ?? metrics.result_sequence;
  const sourceId = detections.source_id ?? "-";

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Monitor</h2>
        <div className="flex items-center gap-3">
          {telemetry.connected && (
            <StatusBadge status="success">
              <span className="flex items-center gap-1">
                <Radio className="w-3 h-3" />
                Pi Connected
              </span>
            </StatusBadge>
          )}
          <StatusBadge status={isConnected && hasFrame ? "success" : "error"}>
            {isConnected && hasFrame ? "LIVE" : "OFFLINE"}
          </StatusBadge>
        </div>
      </div>

      {/* ── Main 2-column layout ── */}
      <div className="grid grid-cols-1 xl:grid-cols-[672px_1fr] gap-6 items-start">

        {/* ── Camera feed ── */}
        <div className="bg-slate-900 rounded-lg overflow-hidden shadow-lg border border-slate-800 w-[672px] max-w-full">
          <div className="w-[640px] h-[480px] max-w-full bg-black relative mx-auto">
            <img ref={imgRef} alt="Robot camera stream" className="h-[480px] w-[640px] object-contain" />
            {!hasFrame && (
              <div className="absolute inset-0 text-slate-500 flex flex-col items-center justify-center gap-2">
                <VideoOff className="w-12 h-12" />
                <span>{isConnected ? "Waiting for stream frames" : "Camera stream disconnected"}</span>
              </div>
            )}
          </div>
          <div className="bg-slate-800 h-11 flex items-center justify-between px-4 text-sm text-slate-300">
            <span>{streamStatus}</span>
            <span className="font-mono text-xs">
              {sourceId !== "-" ? `src: ${sourceId}` : "640×480"}
              {resultSeq != null ? ` · seq #${resultSeq}` : ""}
            </span>
          </div>
        </div>

        {/* ── Right-side panels ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-1 gap-4">

          {/* ─ Adaptive Runtime ─ */}
          <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800 mb-4">
              <Cpu className="w-4 h-4 text-blue-600" />
              Adaptive Runtime
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm mb-3">
              <Metric label="FPS" value={formatValue(fps)} />
              <Metric label="State" value={metrics.state ?? metrics.mode ?? detections.mode ?? "-"} />
              <Metric label="Ready" value={metrics.ready ? "yes" : (metrics.reason ?? "-")} />
              <Metric label="Entities" value={String(entities.length)} />
            </div>
            {/* Latency breakdown */}
            <div className="mt-3 pt-3 border-t border-slate-100">
              <div className="flex items-center gap-1 text-xs font-medium text-slate-500 mb-2">
                <Timer className="w-3 h-3" />
                Latency Breakdown (ms)
              </div>
              <div className="grid grid-cols-4 gap-2">
                <LatencyPill label="Camera" value={camLatency} color="bg-sky-100 text-sky-700" />
                <LatencyPill label="Detector" value={detLatency} color="bg-violet-100 text-violet-700" />
                <LatencyPill label="Fusion" value={fusionLatency} color="bg-amber-100 text-amber-700" />
                <LatencyPill label="Total" value={totalLatency} color="bg-rose-100 text-rose-700" />
              </div>
            </div>
          </section>

          {/* ─ Wheeltec Robot ─ */}
          <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-5">
            <div className="flex items-center justify-between gap-2 mb-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <Navigation className="w-4 h-4 text-emerald-600" />
                Wheeltec Robot
              </div>
              <StatusBadge status={telemetry.connected ? "success" : "error"}>
                {telemetry.connected ? "ONLINE" : "OFFLINE"}
              </StatusBadge>
            </div>

            {/* Battery row */}
            <div className="flex items-center gap-3 mb-3">
              {telemetry.charging ? (
                <BatteryCharging className="w-5 h-5 text-emerald-500" />
              ) : (
                <Battery className={`w-5 h-5 ${(telemetry.battery_percent ?? 100) < 20 ? "text-rose-500" : "text-slate-500"}`} />
              )}
              <div className="flex-1">
                <div className="flex justify-between text-xs text-slate-500 mb-1">
                  <span>Battery{telemetry.charging ? " (charging)" : ""}</span>
                  <span className="font-medium text-slate-800">
                    {telemetry.battery_percent != null ? `${telemetry.battery_percent.toFixed(0)}%` : "-"}
                    {telemetry.voltage != null ? ` · ${telemetry.voltage.toFixed(1)}V` : ""}
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      (telemetry.battery_percent ?? 100) < 20 ? "bg-rose-500" :
                      (telemetry.battery_percent ?? 100) < 50 ? "bg-amber-400" : "bg-emerald-500"
                    }`}
                    style={{ width: `${Math.max(0, Math.min(100, telemetry.battery_percent ?? 0))}%` }}
                  />
                </div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2 text-sm mb-2">
              <Metric label="Vx (m/s)" value={formatRobotValue(telemetry.vx)} />
              <Metric label="Vy (m/s)" value={formatRobotValue(telemetry.vy)} />
              <Metric label="ω (rad/s)" value={formatRobotValue(telemetry.vtheta)} />
            </div>
            <div className="grid grid-cols-3 gap-2 text-sm">
              <Metric label="X (m)" value={formatRobotValue(telemetry.pos_x)} />
              <Metric label="Y (m)" value={formatRobotValue(telemetry.pos_y)} />
              <Metric label="Yaw (°)" value={telemetry.yaw != null ? (telemetry.yaw * 180 / Math.PI).toFixed(1) : "-"} />
            </div>
            {telemetry.imu && Object.keys(telemetry.imu).length > 0 && (
              <div className="mt-2 grid grid-cols-3 gap-2 text-sm">
                <Metric label="Roll (°)" value={telemetry.imu.roll != null ? (telemetry.imu.roll * 180 / Math.PI).toFixed(1) : "-"} />
                <Metric label="Pitch (°)" value={telemetry.imu.pitch != null ? (telemetry.imu.pitch * 180 / Math.PI).toFixed(1) : "-"} />
                <Metric label="Nav Mode" value={telemetry.navigation_mode ?? "-"} />
              </div>
            )}
            {!telemetry.imu && (
              <div className="mt-2 text-xs text-slate-400">
                Nav mode: <span className="font-medium text-slate-700">{telemetry.navigation_mode ?? "-"}</span>
              </div>
            )}
          </section>

          {/* ─ Capture ─ */}
          <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-5">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <Database className="w-4 h-4 text-indigo-600" />
                Capture
              </div>
              <StatusBadge status={isRecording ? "success" : canSave ? "warning" : "default"}>
                {dataset.status}
              </StatusBadge>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm mb-4">
              <Metric label="Mode" value={formatDatasetMode(dataset.dataset_mode)} />
              <Metric label="Session" value={dataset.session_id ? dataset.session_id.slice(0, 12) + "…" : "-"} />
              <Metric label="Frames" value={String(dataset.frame_count ?? 0)} />
              <Metric label="Size" value={formatBytes(dataset.bytes_total ?? 0)} />
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm mb-2">
              <Metric label="Saved" value={dataset.saved ? "yes" : "no"} />
            </div>
            <div className="flex flex-wrap gap-2 mt-2">
              <button
                type="button"
                onClick={startCollection}
                disabled={datasetBusy || isRecording}
                className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Play className="h-4 w-4" />
                Start
              </button>
              <button
                type="button"
                onClick={stopCollection}
                disabled={datasetBusy || !isRecording}
                className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Square className="h-4 w-4" />
                Stop
              </button>
              <button
                type="button"
                onClick={saveCollection}
                disabled={datasetBusy || !canSave}
                className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Save className="h-4 w-4" />
                Save &amp; Download
              </button>
            </div>
            {datasetMessage && <div className="mt-3 text-xs text-rose-600">{datasetMessage}</div>}
          </section>
        </div>
      </div>

      {/* ── Entity / Obstacle tables ── */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <EntityTable
          title="Tracked Entities (Persons)"
          icon={<UserRound className="w-4 h-4 text-emerald-600" />}
          rows={entities}
        />
        <EntityTable
          title="Obstacles"
          icon={<Activity className="w-4 h-4 text-rose-600" />}
          rows={obstacles}
        />
      </div>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-0.5 font-semibold text-slate-900 truncate text-sm">{value}</div>
    </div>
  );
}

function LatencyPill({
  label,
  value,
  color,
}: {
  label: string;
  value?: number;
  color: string;
}) {
  return (
    <div className={`rounded-md px-2 py-1.5 text-center ${color}`}>
      <div className="text-[10px] font-medium opacity-75">{label}</div>
      <div className="text-xs font-bold leading-tight">
        {typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}` : "-"}
      </div>
    </div>
  );
}

function EntityTable({
  title,
  icon,
  rows,
}: {
  title: string;
  icon: ReactNode;
  rows: TrackedEntity[];
}) {
  return (
    <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-5">
      <div className="flex items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          {icon}
          {title}
        </div>
        <span className="text-xs text-slate-400 font-mono">{rows.length} tracked</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500 border-b border-slate-200">
            <tr>
              <th className="py-2 pr-3">ID</th>
              <th className="py-2 pr-3">Conf</th>
              <th className="py-2 pr-3">Dist</th>
              <th className="py-2 pr-3">Intent</th>
              <th className="py-2 pr-3">Pos XY (m)</th>
              <th className="py-2 pr-3">Vel XY (m/s)</th>
              <th className="py-2 pr-3">Hdg (°)</th>
              <th className="py-2">BBox</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="py-4 text-slate-400 text-xs" colSpan={8}>No detections</td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr key={`${row.track_id}-${index}`} className="border-b border-slate-100 last:border-0 text-xs">
                  <td className="py-2 pr-3 font-mono font-bold text-blue-700">#{row.track_id}</td>
                  <td className="py-2 pr-3">{formatPercent(row.confidence)}</td>
                  <td className="py-2 pr-3">{formatDistance(row.distance, row.distance_source)}</td>
                  <td className="py-2 pr-3">
                    {row.intent_name ? (
                      <span className="inline-flex items-center gap-1">
                        <Zap className="w-3 h-3 text-amber-500" />
                        {row.intent_name}
                        {row.intent_confidence != null ? ` ${formatPercent(row.intent_confidence)}` : ""}
                      </span>
                    ) : "-"}
                  </td>
                  <td className="py-2 pr-3 font-mono">
                    {row.position_xyz_m && row.position_xyz_m.length >= 2
                      ? `(${row.position_xyz_m[0].toFixed(2)}, ${row.position_xyz_m[1].toFixed(2)})`
                      : "-"}
                  </td>
                  <td className="py-2 pr-3 font-mono">
                    {row.velocity_xyz_mps && row.velocity_xyz_mps.length >= 2
                      ? `(${row.velocity_xyz_mps[0].toFixed(2)}, ${row.velocity_xyz_mps[1].toFixed(2)})`
                      : "-"}
                  </td>
                  <td className="py-2 pr-3">
                    {row.heading_rad != null ? `${(row.heading_rad * 180 / Math.PI).toFixed(1)}` : "-"}
                  </td>
                  <td className="py-2 font-mono text-[10px] text-slate-500">
                    {row.bbox_xywh && row.bbox_xywh.length === 4
                      ? `[${row.bbox_xywh.map((v) => Math.round(v)).join(",")}]`
                      : "-"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ─── Formatters ───────────────────────────────────────────────────────────────

function formatValue(value?: number) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "-";
}

function formatRobotValue(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "-";
  return value.toFixed(3);
}

function formatPercent(value?: number) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "-";
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDatasetMode(mode?: string | null) {
  if (mode === "rl") return "RL";
  if (mode === "adaptive_raw") return "Adaptive Raw";
  return "Intent CNN";
}

function formatDistance(distance?: number, source?: string) {
  if (typeof distance !== "number" || !Number.isFinite(distance)) return "-";
  const suffix = source ? ` (${source.replace("_", " ")})` : "";
  return `${distance.toFixed(2)}m${suffix}`;
}
