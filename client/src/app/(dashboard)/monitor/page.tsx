"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { useWebSocket } from "@/hooks/useWebSocket";
import { fetchWithAuth } from "@/lib/api";
import { Activity, Download, Play, Radio, Square, Trash2, UserRound, VideoOff } from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

interface DetectionItem {
  track_id: number;
  bbox: number[];
  class_name: string;
  confidence: number;
  distance?: number;
  intent_name?: string;
  intent_confidence?: number;
}

interface DetectionPayload {
  frame_id?: number;
  mode?: string;
  inference_ms?: number;
  persons?: DetectionItem[];
  obstacles?: DetectionItem[];
}

interface MetricsPayload {
  fps?: number;
  inference_ms?: number;
  mode?: string;
  mode_override?: string | null;
  persons?: number;
  obstacles?: number;
}

interface DatasetStatus {
  status: "idle" | "recording" | "stopped" | "discarded";
  dataset_mode?: DatasetMode | null;
  session_id?: string;
  frame_count?: number;
  bytes_total?: number;
  preview_indexes?: number[];
}

type DatasetMode = "intent_cnn" | "rl";

export default function MonitorPage() {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const lastUrlRef = useRef<string | null>(null);
  const previewUrlsRef = useRef<string[]>([]);
  const [hasFrame, setHasFrame] = useState(false);
  const [streamStatus, setStreamStatus] = useState("No frames received");
  const [detections, setDetections] = useState<DetectionPayload>({});
  const [metrics, setMetrics] = useState<MetricsPayload>({});
  const [dataset, setDataset] = useState<DatasetStatus>({ status: "idle" });
  const [datasetBusy, setDatasetBusy] = useState(false);
  const [datasetMessage, setDatasetMessage] = useState("");
  const [datasetMode, setDatasetMode] = useState<DatasetMode>("intent_cnn");
  const [previewUrls, setPreviewUrls] = useState<string[]>([]);

  const { isConnected } = useWebSocket("/ws/video", {
    binaryType: "blob",
    onMessage: (msg) => {
      if (typeof msg.data === "string") {
        setStreamStatus(msg.data);
        return;
      }
      const url = URL.createObjectURL(msg.data as Blob);
      if (imgRef.current) {
        imgRef.current.src = url;
      }
      if (lastUrlRef.current) {
        URL.revokeObjectURL(lastUrlRef.current);
      }
      lastUrlRef.current = url;
      setHasFrame(true);
      setStreamStatus("Receiving frames");
    },
  });

  const clearPreviewUrls = useCallback(() => {
    previewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    previewUrlsRef.current = [];
    setPreviewUrls([]);
  }, []);

  const loadPreviewFrames = useCallback(async (status: DatasetStatus) => {
    clearPreviewUrls();
    const indexes = status.preview_indexes ?? [];
    const urls = await Promise.all(
      indexes.map(async (index) => {
        const response = await fetchWithAuth(`/api/datasets/collection/preview/${index}`);
        return URL.createObjectURL(await response.blob());
      }),
    );
    previewUrlsRef.current = urls;
    setPreviewUrls(urls);
  }, [clearPreviewUrls]);

  useEffect(() => {
    return () => {
      if (lastUrlRef.current) {
        URL.revokeObjectURL(lastUrlRef.current);
      }
      clearPreviewUrls();
    };
  }, [clearPreviewUrls]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const [detRes, metricsRes] = await Promise.all([
          fetchWithAuth("/api/robot/detections"),
          fetchWithAuth("/api/robot/metrics"),
        ]);
        if (cancelled) return;
        setDetections(await detRes.json());
        setMetrics(await metricsRes.json());
      } catch {
        if (!cancelled) {
          setDetections({});
          setMetrics({});
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

  const persons = detections.persons ?? [];
  const obstacles = detections.obstacles ?? [];
  const isRecording = dataset.status === "recording";
  const canReview = dataset.status === "stopped" && (dataset.frame_count ?? 0) > 0;

  const startCollection = async () => {
      setDatasetBusy(true);
      setDatasetMessage("");
      try {
        clearPreviewUrls();
      const response = await fetchWithAuth("/api/datasets/collection/start", {
        method: "POST",
        body: JSON.stringify({ mode: datasetMode }),
      });
      const status = await response.json();
      setDataset(status);
      if (status.dataset_mode === "intent_cnn" || status.dataset_mode === "rl") {
        setDatasetMode(status.dataset_mode);
      }
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
      const status = await response.json();
      setDataset(status);
      if (status.status === "stopped") {
        await loadPreviewFrames(status);
      }
    } catch (error) {
      setDatasetMessage(error instanceof Error ? error.message : "Cannot stop collection");
    } finally {
      setDatasetBusy(false);
    }
  };

  const discardCollection = async () => {
    setDatasetBusy(true);
    setDatasetMessage("");
    try {
      await fetchWithAuth("/api/datasets/collection", { method: "DELETE" });
      clearPreviewUrls();
      setDataset({ status: "idle" });
    } catch (error) {
      setDatasetMessage(error instanceof Error ? error.message : "Cannot discard collection");
    } finally {
      setDatasetBusy(false);
    }
  };

  const saveCollection = async () => {
    setDatasetBusy(true);
    setDatasetMessage("");
    try {
      const response = await fetchWithAuth("/api/datasets/collection/save");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const match = disposition.match(/filename="?([^"]+)"?/);
      const link = document.createElement("a");
      link.href = url;
      link.download = match?.[1] ?? "dataset.zip";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      clearPreviewUrls();
      setDataset({ status: "idle" });
    } catch (error) {
      setDatasetMessage(error instanceof Error ? error.message : "Cannot save dataset");
    } finally {
      setDatasetBusy(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const loadStatus = async () => {
      try {
        const response = await fetchWithAuth("/api/datasets/collection");
        const status = await response.json();
        if (cancelled) return;
        setDataset(status);
        if (status.dataset_mode === "intent_cnn" || status.dataset_mode === "rl") {
          setDatasetMode(status.dataset_mode);
        }
        if (status.status === "stopped") {
          await loadPreviewFrames(status);
        }
      } catch {
        if (!cancelled) {
          setDataset({ status: "idle" });
        }
      }
    };
    void loadStatus();
    return () => {
      cancelled = true;
    };
  }, [loadPreviewFrames]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Monitor</h2>
        <StatusBadge status={isConnected && hasFrame ? "success" : "error"}>
          {isConnected && hasFrame ? "LIVE" : "OFFLINE"}
        </StatusBadge>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[672px_1fr] gap-6 items-start">
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
            <span>640x480</span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-1 gap-4">
          <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800 mb-4">
              <Radio className="w-4 h-4 text-blue-600" />
              AI State
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Metric label="FPS" value={formatValue(metrics.fps)} />
              <Metric label="Inference" value={`${formatValue(metrics.inference_ms ?? detections.inference_ms)} ms`} />
              <Metric label="Mode" value={metrics.mode ?? detections.mode ?? "-"} />
              <Metric label="Override" value={metrics.mode_override ?? "-"} />
            </div>
          </section>

          <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800 mb-4">
              <UserRound className="w-4 h-4 text-emerald-600" />
              Detection Summary
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Metric label="Persons" value={String(persons.length)} />
              <Metric label="Obstacles" value={String(obstacles.length)} />
              <Metric label="Frame" value={String(detections.frame_id ?? "-")} />
              <Metric label="Status" value={hasFrame ? "streaming" : "waiting"} />
            </div>
          </section>

          <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-5">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <Download className="w-4 h-4 text-indigo-600" />
                Dataset
              </div>
              <StatusBadge status={isRecording ? "success" : canReview ? "warning" : "default"}>
                {dataset.status}
              </StatusBadge>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm mb-4">
              <Metric label="Type" value={formatDatasetMode(dataset.dataset_mode ?? datasetMode)} />
              <Metric label="Frames" value={String(dataset.frame_count ?? 0)} />
              <Metric label="Size" value={formatBytes(dataset.bytes_total ?? 0)} />
            </div>
            <div className="mb-4 grid grid-cols-2 rounded-md border border-slate-200 bg-slate-50 p-1 text-sm">
              <button
                type="button"
                onClick={() => setDatasetMode("intent_cnn")}
                disabled={datasetBusy || dataset.status !== "idle"}
                className={`rounded px-3 py-2 font-semibold ${
                  datasetMode === "intent_cnn" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"
                } disabled:cursor-not-allowed disabled:opacity-60`}
              >
                Intent CNN
              </button>
              <button
                type="button"
                onClick={() => setDatasetMode("rl")}
                disabled={datasetBusy || dataset.status !== "idle"}
                className={`rounded px-3 py-2 font-semibold ${
                  datasetMode === "rl" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"
                } disabled:cursor-not-allowed disabled:opacity-60`}
              >
                RL
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
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
                disabled={datasetBusy || !canReview}
                className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Download className="h-4 w-4" />
                Save
              </button>
              <button
                type="button"
                onClick={discardCollection}
                disabled={datasetBusy || dataset.status === "idle"}
                className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
                Clear
              </button>
            </div>
            {datasetMessage && <div className="mt-3 text-sm text-rose-600">{datasetMessage}</div>}
          </section>
        </div>
      </div>

      {canReview && (
        <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800 mb-4">
            <Download className="w-4 h-4 text-indigo-600" />
            Saved Frames
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
            {previewUrls.map((url, index) => (
              <img
                key={url}
                src={url}
                alt={`Collected frame ${index + 1}`}
                className="aspect-video w-full rounded-md border border-slate-200 bg-black object-cover"
              />
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <DetectionTable title="Persons" icon={<UserRound className="w-4 h-4 text-emerald-600" />} rows={persons} />
        <DetectionTable title="Obstacles" icon={<Activity className="w-4 h-4 text-rose-600" />} rows={obstacles} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 font-semibold text-slate-900 truncate">{value}</div>
    </div>
  );
}

function DetectionTable({
  title,
  icon,
  rows,
}: {
  title: string;
  icon: ReactNode;
  rows: DetectionItem[];
}) {
  return (
    <section className="bg-white rounded-lg border border-slate-200 shadow-sm p-5">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-800 mb-4">
        {icon}
        {title}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500 border-b border-slate-200">
            <tr>
              <th className="py-2 pr-3">ID</th>
              <th className="py-2 pr-3">Class</th>
              <th className="py-2 pr-3">Conf</th>
              <th className="py-2 pr-3">Dist</th>
              <th className="py-2 pr-3">Intent</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="py-4 text-slate-400" colSpan={5}>No detections</td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr key={`${row.track_id}-${index}`} className="border-b border-slate-100 last:border-0">
                  <td className="py-2 pr-3 font-mono">{row.track_id}</td>
                  <td className="py-2 pr-3">{row.class_name}</td>
                  <td className="py-2 pr-3">{formatPercent(row.confidence)}</td>
                  <td className="py-2 pr-3">{typeof row.distance === "number" ? `${row.distance.toFixed(2)}m` : "-"}</td>
                  <td className="py-2 pr-3">{row.intent_name ?? "-"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatValue(value?: number) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "-";
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
  return "Intent CNN";
}
