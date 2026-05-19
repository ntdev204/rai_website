"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchWithAuth } from "@/lib/api";
import {
  Bot, Brain, CheckCircle, CloudDownload, Database,
  Download, Play, RefreshCw, Save, Sparkles, Square, Tag, Upload,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

interface CollectionStatus {
  status?: string;
  dataset_mode?: string;
  session_id?: string;
  frame_count?: number;
  sequence_count?: number;
  bytes_total?: number;
  saved?: boolean;
  message?: string | null;
}

interface ServerDatasetStatus {
  status: "empty" | "raw_ready" | "synthetic_ready";
  dataset_stage?: string;
  dataset_id?: string;
  session_id?: string;
  raw_dir?: string;
  synthetic_dir?: string | null;
  synthetic_output_dir?: string | null;
  sequence_count?: number;
  frame_count?: number;
  rejected_count?: number;
  synthetic_file_count?: number;
  synthetic_files?: string[];
  ready_for_training?: boolean;
}

interface SequenceItem {
  sequence_id: string;
  session_id?: string;
  track_id?: string;
  frame_count: number;
  depth_valid_ratio: number;
  synthetic_status?: string;
  metadata: Record<string, unknown>;
  primary_label?: string;
  secondary_label?: string;
}

interface SequenceResponse extends ServerDatasetStatus {
  count: number;
  sequences: SequenceItem[];
}

interface SyntheticResult {
  status?: string;
  synthetic_dir?: string;
  synthetic_output_dir?: string;
  synthetic_file_count?: number;
  synthetic_files?: string[];
  ready_for_training?: boolean;
  message?: string | null;
}

const INTENT_LABELS = ["approach", "follow", "idle", "leave", "erratic", "cross"];

export default function DatasetPage() {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const objectUrlsRef = useRef<string[]>([]);
  const previewUrlRef = useRef<string | null>(null);
  const [collection, setCollection] = useState<CollectionStatus>({});
  const [status, setStatus] = useState<ServerDatasetStatus>({ status: "empty" });
  const [sequences, setSequences] = useState<SequenceItem[]>([]);
  const [selected, setSelected] = useState<SequenceItem | null>(null);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [previewUrl, setPreviewUrl] = useState("");
  const [frameIndex, setFrameIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [synthetic, setSynthetic] = useState<SyntheticResult | null>(null);
  const [labelBusy, setLabelBusy] = useState(false);
  const [primaryLabel, setPrimaryLabel] = useState("");
  const [secondaryLabel, setSecondaryLabel] = useState("");

  const clearThumbs = useCallback(() => {
    objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    objectUrlsRef.current = [];
    setThumbs({});
  }, []);

  const loadCollection = useCallback(async () => {
    const response = await fetchWithAuth("/api/datasets/collection");
    setCollection((await response.json()) as CollectionStatus);
  }, []);

  const loadDataset = useCallback(async () => {
    const response = await fetchWithAuth("/api/datasets/sequences");
    const payload = (await response.json()) as SequenceResponse;
    const nextSequences = payload.sequences ?? [];
    setStatus({
      status: payload.status,
      dataset_stage: payload.dataset_stage,
      dataset_id: payload.dataset_id,
      session_id: payload.session_id,
      raw_dir: payload.raw_dir,
      synthetic_dir: payload.synthetic_dir,
      synthetic_output_dir: payload.synthetic_output_dir,
      sequence_count: payload.sequence_count ?? payload.count,
      frame_count: payload.frame_count,
      rejected_count: payload.rejected_count,
      synthetic_file_count: payload.synthetic_file_count,
      synthetic_files: payload.synthetic_files,
      ready_for_training: payload.ready_for_training,
    });
    setSequences(nextSequences);
    setSelected((current) => {
      if (!current) return nextSequences[0] ?? null;
      return nextSequences.find((s) => s.sequence_id === current.sequence_id) ?? nextSequences[0] ?? null;
    });

    clearThumbs();
    const visible = nextSequences.slice(0, 80);
    const entries = await Promise.all(
      visible.map(async (seq) => {
        const preview = await fetchWithAuth(`/api/datasets/sequences/${seq.sequence_id}/preview/0`);
        const url = URL.createObjectURL(await preview.blob());
        objectUrlsRef.current.push(url);
        return [seq.sequence_id, url] as const;
      }),
    );
    setThumbs(Object.fromEntries(entries));
  }, [clearThumbs]);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadCollection().catch(() => undefined), loadDataset()]);
  }, [loadCollection, loadDataset]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshAll().catch((e) => setMessage(e instanceof Error ? e.message : "Cannot load dataset"));
    }, 0);
    return () => {
      window.clearTimeout(timer);
      clearThumbs();
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, [clearThumbs, refreshAll]);

  useEffect(() => {
    const timer = window.setTimeout(() => setFrameIndex(0), 0);
    return () => window.clearTimeout(timer);
  }, [selected?.sequence_id]);

  useEffect(() => {
    if (selected) {
      setPrimaryLabel(selected.primary_label ?? "");
      setSecondaryLabel(selected.secondary_label ?? "");
    }
  }, [selected]);

  useEffect(() => {
    if (!selected) {
      const timer = window.setTimeout(() => setPreviewUrl(""), 0);
      return () => window.clearTimeout(timer);
    }
    let cancelled = false;
    void fetchWithAuth(`/api/datasets/sequences/${selected.sequence_id}/preview/${frameIndex}`)
      .then(async (response) => {
        const url = URL.createObjectURL(await response.blob());
        if (cancelled) { URL.revokeObjectURL(url); return; }
        if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
        previewUrlRef.current = url;
        setPreviewUrl(url);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [frameIndex, selected]);

  const collectionAction = async (endpoint: string, success: string, body?: unknown) => {
    setBusy(true);
    setMessage("");
    try {
      await fetchWithAuth(endpoint, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      await loadCollection();
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Robot collection request failed");
    } finally { setBusy(false); }
  };

  const importRobotCollection = async () => {
    setBusy(true); setMessage(""); setSynthetic(null);
    try {
      await fetchWithAuth("/api/datasets/collection/import-latest", { method: "POST" });
      await refreshAll();
      setMessage("Robot raw dataset imported into the adaptive raw workspace.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot import robot collection");
    } finally { setBusy(false); }
  };

  const uploadDataset = async (file?: File | null) => {
    if (!file) return;
    setBusy(true); setMessage(""); setSynthetic(null);
    try {
      const data = new FormData();
      data.append("file", file);
      await fetchWithAuth("/api/datasets/upload", { method: "POST", body: data });
      await loadDataset();
      setMessage("Raw dataset uploaded into the adaptive raw workspace.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot upload dataset");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const convertToSynthetic = async () => {
    setBusy(true); setMessage(""); setSynthetic(null);
    try {
      const response = await fetchWithAuth("/api/datasets/autolabel", { method: "POST" });
      const result = (await response.json()) as SyntheticResult;
      setSynthetic(result);
      await loadDataset();
      setMessage("Raw dataset converted to adaptive synthetic HDF5.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot convert dataset");
    } finally { setBusy(false); }
  };

  const downloadDataset = async (kind: "raw" | "synthetic") => {
    setBusy(true); setMessage("");
    try {
      const response = await fetchWithAuth(`/api/datasets/download?kind=${kind}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const match = disposition.match(/filename\*?=(?:UTF-8'')?\"?([^";]+)\"?/i);
      const link = document.createElement("a");
      link.href = url;
      link.download = decodeURIComponent(match?.[1] ?? `adaptive_context_aware_${kind}_dataset.zip`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot download dataset");
    } finally { setBusy(false); }
  };

  const saveLabel = async () => {
    if (!selected || !primaryLabel) return;
    setLabelBusy(true);
    try {
      await fetchWithAuth(`/api/datasets/sequences/${selected.sequence_id}/label`, {
        method: "POST",
        body: JSON.stringify({ primary_label: primaryLabel, secondary_label: secondaryLabel || null }),
      });
      await loadDataset();
      setMessage(`Sequence ${selected.sequence_id.slice(0, 8)}… labeled as "${primaryLabel}".`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot save label");
    } finally { setLabelBusy(false); }
  };

  const canConvert = status.status === "raw_ready" || status.status === "synthetic_ready";
  const collectionRecording = collection.status === "recording";
  const syntheticReady = status.status === "synthetic_ready";
  const syntheticFiles = status.synthetic_files ?? synthetic?.synthetic_files ?? [];
  const collectionMode = collection.dataset_mode ?? "intent_cnn";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-800">Dataset</h2>
          <div className="mt-1 text-sm text-slate-500">
            Robot capture → raw sequences → adaptive synthetic HDF5 → training
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <input ref={fileRef} type="file" accept=".zip,application/zip" className="hidden"
            onChange={(e) => uploadDataset(e.target.files?.[0])} />
          <button type="button" onClick={() => fileRef.current?.click()} disabled={busy}
            className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            <Upload className="h-4 w-4" /> Upload raw zip
          </button>
          <button type="button" onClick={() => refreshAll()} disabled={busy}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
          <button type="button" onClick={convertToSynthetic} disabled={busy || !canConvert}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            <Sparkles className="h-4 w-4" /> Convert to synthetic
          </button>
          <button type="button" onClick={() => downloadDataset(syntheticReady ? "synthetic" : "raw")}
            disabled={busy || status.status === "empty"}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50">
            <Download className="h-4 w-4" /> Download {syntheticReady ? "HDF5" : "raw"}
          </button>
        </div>
      </div>

      {/* Pipeline steps */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1">
        {[
          { icon: <Bot className="w-4 h-4" />, label: "1. Robot Capture", active: collectionRecording, done: !!collection.session_id },
          { icon: <Save className="w-4 h-4" />, label: "2. Save & Import", active: false, done: status.status !== "empty" },
          { icon: <Tag className="w-4 h-4" />, label: "3. Label Sequences", active: false, done: sequences.some((s) => s.primary_label) },
          { icon: <Sparkles className="w-4 h-4" />, label: "4. Synthetic HDF5", active: false, done: syntheticReady },
          { icon: <Brain className="w-4 h-4" />, label: "5. Training", active: false, done: false },
        ].map((step, i) => (
          <div key={i} className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium whitespace-nowrap border ${
            step.done ? "bg-emerald-50 border-emerald-200 text-emerald-700" :
            step.active ? "bg-blue-50 border-blue-300 text-blue-700 animate-pulse" :
            "bg-slate-50 border-slate-200 text-slate-500"
          }`}>
            {step.done ? <CheckCircle className="w-3.5 h-3.5" /> : step.icon}
            {step.label}
          </div>
        ))}
      </div>

      {/* Robot Collection */}
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Bot className="h-4 w-4 text-blue-600" /> Robot Collection
            <span className="text-xs font-normal text-slate-400">
              (wheeltec_ros2 → adaptive-context-aware ZMQ sensor ingest port 5555)
            </span>
          </div>
          <StatusBadge status={collectionRecording ? "success" : "default"}>
            {collection.status ?? "unknown"}
          </StatusBadge>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5 mb-4">
          <Metric label="Mode" value={formatMode(collectionMode)} />
          <Metric label="Session ID" value={collection.session_id ? collection.session_id.slice(0, 12) + "…" : "-"} />
          <Metric label="Frames" value={String(collection.frame_count ?? "-")} />
          <Metric label="Tracks" value={String(collection.sequence_count ?? "-")} />
          <Metric label="Size" value={formatBytes(collection.bytes_total)} />
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button"
            onClick={() => collectionAction("/api/datasets/collection/start", "Robot collection started.", { mode: "adaptive_raw" })}
            disabled={busy || collectionRecording}
            className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            <Play className="h-4 w-4" /> Start
          </button>
          <button type="button"
            onClick={() => collectionAction("/api/datasets/collection/stop", "Robot collection stopped.")}
            disabled={busy || !collectionRecording}
            className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            <Square className="h-4 w-4" /> Stop
          </button>
          <button type="button"
            onClick={() => collectionAction("/api/datasets/collection/save", "Robot raw collection saved.")}
            disabled={busy || collectionRecording || !collection.session_id}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50">
            <Save className="h-4 w-4" /> Save raw
          </button>
          <button type="button" onClick={importRobotCollection}
            disabled={busy || collectionRecording || !collection.session_id}
            className="inline-flex items-center gap-2 rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800 disabled:opacity-50">
            <CloudDownload className="h-4 w-4" /> Import raw
          </button>
        </div>
      </section>

      {/* Dataset overview stats */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <Metric label="Dataset ID" value={status.dataset_id ?? "-"} />
        <Metric label="Status" value={status.dataset_stage ?? status.status} />
        <Metric label="Sequences" value={String(status.sequence_count ?? sequences.length)} />
        <Metric label="Frames" value={String(status.frame_count ?? "-")} />
        <Metric label="Rejected" value={String(status.rejected_count ?? 0)} />
        <Metric label="Synthetic H5" value={String(status.synthetic_file_count ?? 0)} />
      </section>

      {message && (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">{message}</div>
      )}

      {/* Synthetic Output */}
      {(synthetic || syntheticReady) && (
        <section className="rounded-lg border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-emerald-800">
            <Database className="h-4 w-4" /> Synthetic Output (HDF5)
          </div>
          <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3 mb-3">
            <Metric label="Ready For Training" value={status.ready_for_training ? "✓ yes" : "no"} />
            <Metric label="Output Dir" value={status.synthetic_output_dir ?? synthetic?.synthetic_output_dir ?? "-"} />
            <Metric label="H5 Files" value={String(status.synthetic_file_count ?? synthetic?.synthetic_file_count ?? 0)} />
          </div>
          <div className="flex flex-wrap gap-2">
            {syntheticFiles.length > 0 ? (
              syntheticFiles.map((file) => (
                <span key={file} className="rounded-md bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-800">{file}</span>
              ))
            ) : (
              <span className="text-sm text-slate-500">No synthetic files yet.</span>
            )}
          </div>
        </section>
      )}

      {/* Sequences + preview */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_420px]">
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <Database className="h-4 w-4 text-indigo-600" /> Raw Sequences
            </div>
            <StatusBadge status={syntheticReady ? "success" : status.status === "raw_ready" ? "warning" : "default"}>
              {status.dataset_stage ?? status.status}
            </StatusBadge>
          </div>

          {sequences.length === 0 ? (
            <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
              No raw dataset imported.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
              {sequences.map((seq) => (
                <button key={seq.sequence_id} type="button" onClick={() => setSelected(seq)}
                  className={`group overflow-hidden rounded-md border bg-slate-50 text-left ${
                    selected?.sequence_id === seq.sequence_id ? "border-blue-500 ring-2 ring-blue-100" : "border-slate-200"
                  }`}>
                  {thumbs[seq.sequence_id] ? (
                    <img src={thumbs[seq.sequence_id]} alt={seq.sequence_id} className="h-28 w-full bg-black object-contain" />
                  ) : (
                    <div className="h-28 w-full bg-slate-200" />
                  )}
                  <div className="space-y-1 px-2 py-2">
                    <div className="truncate text-xs font-semibold text-slate-800">{seq.track_id ?? seq.sequence_id.slice(0, 10)}</div>
                    <div className="flex items-center justify-between gap-1 text-[10px] text-slate-500">
                      <span>K={seq.frame_count}</span>
                      {seq.primary_label ? (
                        <span className="rounded bg-blue-100 px-1 text-blue-700 font-medium">{seq.primary_label}</span>
                      ) : (
                        <span className="text-amber-500">{seq.synthetic_status ?? "pending"}</span>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Sequence preview panel */}
        <aside className="sticky top-4 h-[calc(100vh-10rem)] overflow-hidden rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Database className="h-4 w-4 text-blue-600" /> Sequence Preview
          </div>
          {selected ? (
            <div className="h-full space-y-4 overflow-y-auto pr-1">
              {previewUrl && (
                <img src={previewUrl} alt={selected.sequence_id}
                  className="h-48 w-full rounded-md border border-slate-200 bg-black object-contain" />
              )}
              <div className="space-y-2">
                <input type="range" min={0} max={Math.max(0, selected.frame_count - 1)}
                  value={Math.min(frameIndex, Math.max(0, selected.frame_count - 1))}
                  onChange={(e) => setFrameIndex(Number(e.target.value))} className="w-full" />
                <div className="flex justify-between text-xs text-slate-500">
                  <span>Frame {Math.min(frameIndex + 1, selected.frame_count)}</span>
                  <span>K={selected.frame_count}</span>
                </div>
              </div>

              <div className="space-y-2 text-sm">
                <Detail label="Sequence" value={selected.sequence_id} />
                <Detail label="Session" value={selected.session_id ?? "-"} />
                <Detail label="Track ID" value={selected.track_id ?? "-"} />
                <Detail label="Depth Valid" value={formatPercent(selected.depth_valid_ratio)} />
                <Detail label="Synthetic" value={selected.synthetic_status ?? "pending"} />
                <Detail label="Primary Label" value={selected.primary_label ?? "(unlabeled)"} />
                <Detail label="Secondary Label" value={selected.secondary_label ?? "-"} />
              </div>

              {/* Label editor */}
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
                <div className="flex items-center gap-1 text-xs font-semibold text-slate-700">
                  <Tag className="w-3 h-3" /> Label Sequence
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Primary Intent</label>
                  <select value={primaryLabel} onChange={(e) => setPrimaryLabel(e.target.value)}
                    className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm">
                    <option value="">— select —</option>
                    {INTENT_LABELS.map((l) => <option key={l} value={l}>{l}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Secondary Label (optional)</label>
                  <input value={secondaryLabel} onChange={(e) => setSecondaryLabel(e.target.value)}
                    placeholder="e.g. slow, fast…"
                    className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
                </div>
                <button type="button" onClick={saveLabel} disabled={labelBusy || !primaryLabel}
                  className="inline-flex items-center gap-2 rounded bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
                  <CheckCircle className="w-3.5 h-3.5" /> Save Label
                </button>
              </div>

              <pre className="max-h-64 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
                {JSON.stringify(selected.metadata, null, 2)}
              </pre>
            </div>
          ) : (
            <div className="text-sm text-slate-500">Select a sequence.</div>
          )}
        </aside>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 truncate font-semibold text-slate-900 text-sm">{value}</div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-3 py-2">
      <span className="text-slate-500 text-xs shrink-0">{label}</span>
      <span className="truncate font-medium text-slate-900 text-xs text-right">{value}</span>
    </div>
  );
}

function formatPercent(value?: number) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "-";
}

function formatBytes(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatMode(mode: string) {
  if (mode === "adaptive_raw") return "Adaptive Raw";
  if (mode === "rl") return "RL";
  return "Intent CNN";
}
