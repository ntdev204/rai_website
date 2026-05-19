"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchWithAuth } from "@/lib/api";
import {
  BrainCircuit, CheckCircle, Clock, Cpu, Database,
  RefreshCw, Square, TrendingUp, Zap,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

interface TrainingConfig {
  dataset: string;
  output: string;
  epochs: number;
  batch_size: number;
  lr: number;
  lambda_dir: number;
  val_split: number;
  workers: number;
  device: "auto" | "cuda" | "cpu";
  temporal_window: number;
  freeze_blocks: number;
  save_every: number;
  replay_buffer: number;
  ewc_lambda: number;
  confidence_threshold: number;
  margin_threshold: number;
  resume?: string | null;
  epochs_are_additional: boolean;
  allow_unreviewed_erratic: boolean;
  distill_from?: string | null;
}

interface TrainingDefaults extends Partial<TrainingConfig> {
  dataset_source?: string;
}

interface TrainingMetric {
  epoch?: number;
  lr?: number;
  train_loss?: number;
  train_acc?: number;
  val_loss?: number;
  val_acc?: number;
  train_intent_loss?: number;
  train_dir_loss?: number;
  val_intent_loss?: number;
  val_dir_loss?: number;
}

interface TrainingStatus {
  job_id?: string;
  status: "idle" | "running" | "stopping" | "completed" | "failed";
  started_at?: number | null;
  finished_at?: number | null;
  return_code?: number | null;
  dataset?: string;
  output?: string;
  logs?: string[];
  metrics?: TrainingMetric[];
  latest_epoch?: TrainingMetric | null;
  best_checkpoint?: {
    path?: string;
    epoch?: number;
    val_loss?: number;
    val_accuracy?: number;
    temperature?: number;
    ece?: number;
    error?: string;
  } | null;
  error?: string | null;
}

const fallbackConfig: TrainingConfig = {
  dataset: "/data/synthetic",
  output: "/workspace/models/cnn_intent",
  epochs: 30,
  batch_size: 32,
  lr: 0.0003,
  lambda_dir: 0.5,
  val_split: 0.15,
  workers: 4,
  device: "auto",
  temporal_window: 15,
  freeze_blocks: 10,
  save_every: 5,
  replay_buffer: 5000,
  ewc_lambda: 5000,
  confidence_threshold: 0.55,
  margin_threshold: 0.12,
  resume: "",
  epochs_are_additional: false,
  allow_unreviewed_erratic: false,
  distill_from: "",
};

export default function TrainingPage() {
  const [config, setConfig] = useState<TrainingConfig>(fallbackConfig);
  const [status, setStatus] = useState<TrainingStatus>({ status: "idle" });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const loadStatus = useCallback(async () => {
    const response = await fetchWithAuth("/api/training/status");
    setStatus(await response.json());
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [defaultsRes, statusRes] = await Promise.all([
          fetchWithAuth("/api/training/defaults"),
          fetchWithAuth("/api/training/status"),
        ]);
        if (cancelled) return;
        const defaults = (await defaultsRes.json()) as TrainingDefaults;
        setConfig({
          ...fallbackConfig,
          ...defaults,
          dataset: defaults.dataset_source === "server_synthetic_dataset"
            ? "latest"
            : defaults.dataset ?? fallbackConfig.dataset,
        });
        setStatus(await statusRes.json());
      } catch (error) {
        if (!cancelled) setMessage(error instanceof Error ? error.message : "Cannot load training API");
      }
    };
    void load();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (status.status !== "running" && status.status !== "stopping") return;
    const timer = setInterval(() => void loadStatus().catch(() => undefined), 1500);
    return () => clearInterval(timer);
  }, [loadStatus, status.status]);

  const startTraining = async () => {
    setBusy(true); setMessage("");
    try {
      const body = { ...config, resume: config.resume || null, distill_from: config.distill_from || null };
      const response = await fetchWithAuth("/api/training/start", { method: "POST", body: JSON.stringify(body) });
      setStatus(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot start training");
    } finally { setBusy(false); }
  };

  const stopTraining = async () => {
    setBusy(true); setMessage("");
    try {
      const response = await fetchWithAuth("/api/training/stop", { method: "POST" });
      setStatus(await response.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot stop training");
    } finally { setBusy(false); }
  };

  const running = status.status === "running" || status.status === "stopping";
  const metrics = status.metrics ?? [];
  const latest = status.latest_epoch;
  const progress = latest?.epoch && config.epochs
    ? Math.round((latest.epoch / config.epochs) * 100)
    : 0;
  const elapsed = status.started_at
    ? Math.round((Date.now() / 1000) - status.started_at)
    : null;

  function update<K extends keyof TrainingConfig>(key: K, value: TrainingConfig[K]) {
    setConfig((c) => ({ ...c, [key]: value }));
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-800">Training</h2>
          <div className="mt-1 text-sm text-slate-500">
            Intent CNN / TCN — adaptive-context-aware training server
          </div>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => loadStatus()} disabled={busy}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
          <button type="button" onClick={startTraining} disabled={busy || running}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            <Zap className="h-4 w-4" /> Start
          </button>
          <button type="button" onClick={stopTraining} disabled={busy || !running}
            className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            <Square className="h-4 w-4" /> Stop
          </button>
        </div>
      </div>

      {/* Status overview */}
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Cpu className="w-4 h-4 text-blue-600" /> Job Status
          </div>
          <StatusBadge status={running ? "success" : status.status === "failed" ? "error" : status.status === "completed" ? "success" : "default"}>
            {status.status.toUpperCase()}
          </StatusBadge>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5 mb-4">
          <Metric label="Job ID" value={status.job_id ? status.job_id.slice(0, 10) + "…" : "-"} />
          <Metric label="Epoch" value={latest?.epoch ? `${latest.epoch} / ${config.epochs}` : "-"} />
          <Metric label="Val Acc" value={formatPercent(latest?.val_acc)} />
          <Metric label="Val Loss" value={formatNumber(latest?.val_loss)} />
          <Metric label="Dataset" value={status.dataset ? shortenPath(status.dataset) : config.dataset ? shortenPath(config.dataset) : "-"} />
        </div>

        {/* Progress bar */}
        {(running || status.status === "completed") && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-slate-500">
              <span className="flex items-center gap-1">
                <TrendingUp className="w-3 h-3" />
                Progress: {progress}%
              </span>
              {elapsed != null && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {formatElapsed(elapsed)}
                </span>
              )}
            </div>
            <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${running ? "bg-blue-500" : "bg-emerald-500"}`}
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </section>

      {message && (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">{message}</div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[420px_1fr]">
        {/* Parameters */}
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <BrainCircuit className="h-4 w-4 text-blue-600" /> Parameters
          </div>
          <div className="space-y-3">
            <TextInput label="Dataset path" value={config.dataset} onChange={(v) => update("dataset", v)} />
            <TextInput label="Output path" value={config.output} onChange={(v) => update("output", v)} />
            <div className="grid grid-cols-2 gap-3">
              <NumberInput label="Epochs" value={config.epochs} onChange={(v) => update("epochs", v)} />
              <NumberInput label="Batch size" value={config.batch_size} onChange={(v) => update("batch_size", v)} />
              <NumberInput label="Learning rate" value={config.lr} step="0.0001" onChange={(v) => update("lr", v)} />
              <NumberInput label="Val split" value={config.val_split} step="0.01" onChange={(v) => update("val_split", v)} />
              <NumberInput label="Temporal window" value={config.temporal_window} onChange={(v) => update("temporal_window", v)} />
              <NumberInput label="Workers" value={config.workers} onChange={(v) => update("workers", v)} />
              <NumberInput label="λ direction" value={config.lambda_dir} step="0.1" onChange={(v) => update("lambda_dir", v)} />
              <NumberInput label="Freeze blocks" value={config.freeze_blocks} onChange={(v) => update("freeze_blocks", v)} />
              <NumberInput label="Save every N" value={config.save_every} onChange={(v) => update("save_every", v)} />
              <NumberInput label="Replay buffer" value={config.replay_buffer} onChange={(v) => update("replay_buffer", v)} />
              <NumberInput label="EWC λ" value={config.ewc_lambda} onChange={(v) => update("ewc_lambda", v)} />
              <NumberInput label="Conf threshold" value={config.confidence_threshold} step="0.01" onChange={(v) => update("confidence_threshold", v)} />
              <NumberInput label="Margin threshold" value={config.margin_threshold} step="0.01" onChange={(v) => update("margin_threshold", v)} />
            </div>
            <label className="block text-sm">
              <span className="text-xs font-medium text-slate-500">Device</span>
              <select value={config.device}
                onChange={(e) => update("device", e.target.value as TrainingConfig["device"])}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
                <option value="auto">auto</option>
                <option value="cuda">cuda</option>
                <option value="cpu">cpu</option>
              </select>
            </label>
            <TextInput label="Resume checkpoint" value={config.resume ?? ""} onChange={(v) => update("resume", v)} />
            <TextInput label="Distill from" value={config.distill_from ?? ""} onChange={(v) => update("distill_from", v)} />
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={config.epochs_are_additional}
                onChange={(e) => update("epochs_are_additional", e.target.checked)} />
              Epochs are additional
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={config.allow_unreviewed_erratic}
                onChange={(e) => update("allow_unreviewed_erratic", e.target.checked)} />
              Allow unreviewed ERRATIC
            </label>
          </div>
        </section>

        <div className="space-y-6">
          {/* Best checkpoint */}
          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
              <CheckCircle className="h-4 w-4 text-emerald-600" /> Best Checkpoint
            </div>
            {status.best_checkpoint?.error ? (
              <div className="text-sm text-rose-600">{status.best_checkpoint.error}</div>
            ) : (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Metric label="Best Epoch" value={String(status.best_checkpoint?.epoch ?? "-")} />
                <Metric label="Val Loss" value={formatNumber(status.best_checkpoint?.val_loss)} />
                <Metric label="Val Acc" value={formatPercent(status.best_checkpoint?.val_accuracy)} />
                <Metric label="Temperature" value={formatNumber(status.best_checkpoint?.temperature)} />
                <Metric label="ECE" value={formatNumber(status.best_checkpoint?.ece)} />
                <Metric label="Output Path" value={status.output ? shortenPath(status.output) : "-"} />
              </div>
            )}
          </section>

          {/* Epoch metrics table */}
          <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <Database className="h-4 w-4 text-indigo-600" /> Epoch Metrics
              </div>
              <StatusBadge status={running ? "success" : status.status === "failed" ? "error" : "default"}>
                {metrics.length} rows
              </StatusBadge>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="border-b border-slate-200 text-left uppercase text-slate-500">
                  <tr>
                    <th className="py-2 pr-3">Epoch</th>
                    <th className="py-2 pr-3">LR</th>
                    <th className="py-2 pr-3">Train Loss</th>
                    <th className="py-2 pr-3">Train Acc</th>
                    <th className="py-2 pr-3">Val Loss</th>
                    <th className="py-2 pr-3">Val Acc</th>
                    <th className="py-2 pr-3">Train Dir</th>
                    <th className="py-2 pr-3">Val Dir</th>
                    <th className="py-2">Val Intent</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.length === 0 ? (
                    <tr><td colSpan={9} className="py-4 text-slate-400">No metrics yet.</td></tr>
                  ) : (
                    metrics.slice(-20).map((row) => (
                      <tr key={row.epoch}
                        className={`border-b border-slate-100 last:border-0 ${row.epoch === latest?.epoch ? "bg-blue-50" : ""}`}>
                        <td className="py-2 pr-3 font-mono font-bold">{row.epoch ?? "-"}</td>
                        <td className="py-2 pr-3">{formatScientific(row.lr)}</td>
                        <td className="py-2 pr-3">{formatNumber(row.train_loss)}</td>
                        <td className="py-2 pr-3">{formatPercent(row.train_acc)}</td>
                        <td className="py-2 pr-3">{formatNumber(row.val_loss)}</td>
                        <td className="py-2 pr-3 font-semibold">{formatPercent(row.val_acc)}</td>
                        <td className="py-2 pr-3">{formatNumber(row.train_dir_loss)}</td>
                        <td className="py-2 pr-3">{formatNumber(row.val_dir_loss)}</td>
                        <td className="py-2">{formatNumber(row.val_intent_loss)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* Training log */}
          <section className="rounded-lg border border-slate-200 bg-slate-950 p-5 shadow-sm">
            <div className="mb-3 text-sm font-semibold text-slate-100">Training Log</div>
            <pre className="h-72 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-200">
              {(status.logs ?? []).join("\n") || "No logs yet."}
            </pre>
          </section>
        </div>
      </div>
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 truncate font-semibold text-slate-900 text-sm">{value}</div>
    </div>
  );
}

function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block text-sm">
      <span className="text-xs font-medium text-slate-500">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
    </label>
  );
}

function NumberInput({ label, value, step = "1", onChange }: {
  label: string; value: number; step?: string; onChange: (v: number) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="text-xs font-medium text-slate-500">{label}</span>
      <input type="number" step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
    </label>
  );
}

// ─── Formatters ────────────────────────────────────────────────────────────────

function formatNumber(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "-";
}

function formatPercent(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "-";
}

function formatScientific(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? value.toExponential(2) : "-";
}

function formatElapsed(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function shortenPath(p: string) {
  const parts = p.replace(/\\/g, "/").split("/");
  return parts.length > 3 ? `…/${parts.slice(-2).join("/")}` : p;
}
