"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchWithAuth } from "@/lib/api";
import {
  Bot,
  CheckCircle2,
  CloudDownload,
  Database,
  Download,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  Square,
  Tag,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

const INTENT_LABELS = ["STATIONARY", "APPROACHING", "DEPARTING", "CROSSING", "ERRATIC", "UNCERTAIN"];

interface CollectionStatus {
  status?: string;
  dataset_type?: string;
  session_id?: string;
  frame_count?: number;
  sequence_count?: number;
  bytes_total?: number;
  error?: string | null;
}

interface ServerDatasetStatus {
  status: "empty" | "raw_ready" | "auto_labeled";
  dataset_stage?: string;
  dataset_id?: string;
  session_id?: string;
  raw_dir?: string;
  labeled_dir?: string | null;
  train_dataset_dir?: string | null;
  sequence_count?: number;
  frame_count?: number;
  rejected_count?: number;
  class_counts?: Record<string, number>;
  review_pending?: Record<string, number>;
  ready_for_training?: boolean;
}

interface SequenceLabel {
  primary_label: string;
  secondary_label?: string | null;
  label_source: string;
  confidence: number;
  review_status: string;
  human_final_required?: boolean;
  labeling_agents?: Record<string, boolean>;
  notes?: string;
}

interface SequenceItem {
  sequence_id: string;
  session_id?: string;
  track_id?: string;
  frame_count: number;
  depth_valid_ratio: number;
  label?: SequenceLabel | null;
  metadata: Record<string, unknown>;
}

interface SequenceResponse extends ServerDatasetStatus {
  count: number;
  sequences: SequenceItem[];
}

interface AutolabelResult {
  status?: string;
  train_dataset_dir?: string;
  sequence_count?: number;
  class_counts?: Record<string, number>;
  review_pending?: Record<string, number>;
  ready_for_training?: boolean;
  error?: string | null;
}

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
  const [labelDraft, setLabelDraft] = useState("UNCERTAIN");
  const [secondaryDraft, setSecondaryDraft] = useState("crossing_right");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [autolabel, setAutolabel] = useState<AutolabelResult | null>(null);

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
      labeled_dir: payload.labeled_dir,
      train_dataset_dir: payload.train_dataset_dir,
      sequence_count: payload.sequence_count ?? payload.count,
      frame_count: payload.frame_count,
      rejected_count: payload.rejected_count,
      class_counts: payload.class_counts,
      review_pending: payload.review_pending,
      ready_for_training: payload.ready_for_training,
    });
    setSequences(nextSequences);
    setSelected((current) => {
      if (!current) return nextSequences[0] ?? null;
      return nextSequences.find((sequence) => sequence.sequence_id === current.sequence_id) ?? nextSequences[0] ?? null;
    });

    clearThumbs();
    const visible = nextSequences.slice(0, 80);
    const entries = await Promise.all(
      visible.map(async (sequence) => {
        const preview = await fetchWithAuth(`/api/datasets/sequences/${sequence.sequence_id}/preview/0`);
        const url = URL.createObjectURL(await preview.blob());
        objectUrlsRef.current.push(url);
        return [sequence.sequence_id, url] as const;
      }),
    );
    setThumbs(Object.fromEntries(entries));
  }, [clearThumbs]);

  const refreshAll = useCallback(async () => {
    await Promise.all([
      loadCollection().catch(() => undefined),
      loadDataset(),
    ]);
  }, [loadCollection, loadDataset]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshAll().catch((error) => {
        setMessage(error instanceof Error ? error.message : "Cannot load dataset");
      });
    }, 0);
    return () => {
      window.clearTimeout(timer);
      clearThumbs();
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, [clearThumbs, refreshAll]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setFrameIndex(0);
      setLabelDraft(selected?.label?.primary_label ?? "UNCERTAIN");
      setSecondaryDraft(selected?.label?.secondary_label ?? "crossing_right");
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selected?.sequence_id, selected?.label?.primary_label, selected?.label?.secondary_label]);

  useEffect(() => {
    if (!selected) {
      const timer = window.setTimeout(() => setPreviewUrl(""), 0);
      return () => window.clearTimeout(timer);
    }
    let cancelled = false;
    void fetchWithAuth(`/api/datasets/sequences/${selected.sequence_id}/preview/${frameIndex}`)
      .then(async (response) => {
        const url = URL.createObjectURL(await response.blob());
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
        previewUrlRef.current = url;
        setPreviewUrl(url);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [frameIndex, selected]);

  const collectionAction = async (endpoint: string, success: string, body?: unknown) => {
    setBusy(true);
    setMessage("");
    try {
      await fetchWithAuth(endpoint, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      await loadCollection();
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Robot collection request failed");
    } finally {
      setBusy(false);
    }
  };

  const importRobotCollection = async () => {
    setBusy(true);
    setMessage("");
    setAutolabel(null);
    try {
      await fetchWithAuth("/api/datasets/collection/import-latest", { method: "POST" });
      await refreshAll();
      setMessage("Robot collection imported as whole-track K-frame sequences.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot import robot collection");
    } finally {
      setBusy(false);
    }
  };

  const uploadDataset = async (file?: File | null) => {
    if (!file) return;
    setBusy(true);
    setMessage("");
    setAutolabel(null);
    try {
      const data = new FormData();
      data.append("file", file);
      await fetchWithAuth("/api/datasets/upload", {
        method: "POST",
        body: data,
      });
      await loadDataset();
      setMessage("Raw sequence dataset uploaded and normalized on the server.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot upload dataset");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const runAutolabel = async () => {
    setBusy(true);
    setMessage("");
    setAutolabel(null);
    try {
      const response = await fetchWithAuth("/api/datasets/autolabel", { method: "POST" });
      const result = (await response.json()) as AutolabelResult;
      setAutolabel(result);
      await loadDataset();
      setMessage("Server auto-label finished. Review low-confidence, ERRATIC, and disagreement cases before training.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot run auto label");
    } finally {
      setBusy(false);
    }
  };

  const saveManualLabel = async () => {
    if (!selected) return;
    setBusy(true);
    setMessage("");
    try {
      await fetchWithAuth(`/api/datasets/sequences/${selected.sequence_id}/label`, {
        method: "POST",
        body: JSON.stringify({
          primary_label: labelDraft,
          secondary_label: labelDraft === "CROSSING" ? secondaryDraft : null,
        }),
      });
      await loadDataset();
      setMessage("Manual label saved and training manifest regenerated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot save label");
    } finally {
      setBusy(false);
    }
  };

  const downloadDataset = async (kind: "raw" | "labeled") => {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetchWithAuth(`/api/datasets/download?kind=${kind}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
      const link = document.createElement("a");
      link.href = url;
      link.download = decodeURIComponent(match?.[1] ?? `context_aware_${kind}_dataset.zip`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot download dataset");
    } finally {
      setBusy(false);
    }
  };

  const canAutolabel = status.status === "raw_ready" || status.status === "auto_labeled";
  const classCounts = status.class_counts ?? autolabel?.class_counts ?? {};
  const reviewPending = status.review_pending ?? autolabel?.review_pending ?? {};
  const collectionRecording = collection.status === "recording";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-800">Dataset</h2>
          <div className="mt-1 text-sm text-slate-500">Whole-track collection, labeling, review, and training handoff</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            onChange={(event) => uploadDataset(event.target.files?.[0])}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Upload className="h-4 w-4" />
            Upload zip
          </button>
          <button
            type="button"
            onClick={() => refreshAll()}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            type="button"
            onClick={runAutolabel}
            disabled={busy || !canAutolabel}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            Auto label
          </button>
          <button
            type="button"
            onClick={() => downloadDataset(status.status === "auto_labeled" ? "labeled" : "raw")}
            disabled={busy || status.status === "empty"}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            Download
          </button>
        </div>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Bot className="h-4 w-4 text-blue-600" />
            Robot Collection
          </div>
          <StatusBadge status={collectionRecording ? "success" : collection.error ? "error" : "default"}>
            {collection.status ?? "unknown"}
          </StatusBadge>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Metric label="Robot Session" value={collection.session_id ?? "-"} />
          <Metric label="Robot Frames" value={String(collection.frame_count ?? "-")} />
          <Metric label="Robot Tracks" value={String(collection.sequence_count ?? "-")} />
          <Metric label="Bytes" value={formatBytes(collection.bytes_total)} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => collectionAction("/api/datasets/collection/start", "Robot collection started.", { mode: "intent_cnn" })}
            disabled={busy || collectionRecording}
            className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            Start
          </button>
          <button
            type="button"
            onClick={() => collectionAction("/api/datasets/collection/stop", "Robot collection stopped.")}
            disabled={busy || !collectionRecording}
            className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Square className="h-4 w-4" />
            Stop
          </button>
          <button
            type="button"
            onClick={() => collectionAction("/api/datasets/collection/save", "Robot collection saved.")}
            disabled={busy || collectionRecording || !collection.session_id}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            Save
          </button>
          <button
            type="button"
            onClick={importRobotCollection}
            disabled={busy || collectionRecording || !collection.session_id}
            className="inline-flex items-center gap-2 rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <CloudDownload className="h-4 w-4" />
            Import
          </button>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-5">
        <Metric label="Dataset" value={status.dataset_id ?? "-"} />
        <Metric label="Status" value={status.status} />
        <Metric label="Sequences" value={String(status.sequence_count ?? sequences.length)} />
        <Metric label="Frames" value={String(status.frame_count ?? "-")} />
        <Metric label="Rejected" value={String(status.rejected_count ?? 0)} />
      </section>

      {message && (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
          {message}
        </div>
      )}

      {(autolabel || status.status === "auto_labeled") && (
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            Label Summary
          </div>
          <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
            <Metric label="Ready For Training" value={status.ready_for_training ? "yes" : "needs review"} />
            <Metric label="Train Dataset" value={status.train_dataset_dir ?? autolabel?.train_dataset_dir ?? "-"} />
            <Metric label="Review Pending" value={formatCounts(reviewPending)} />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(classCounts).map(([label, count]) => (
              <span key={label} className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
                {label}: {count}
              </span>
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_400px]">
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <Database className="h-4 w-4 text-indigo-600" />
              K-Frame Tracks
            </div>
            <StatusBadge status={status.status === "auto_labeled" ? "success" : status.status === "raw_ready" ? "warning" : "default"}>
              {status.dataset_stage ?? status.status}
            </StatusBadge>
          </div>

          {sequences.length === 0 ? (
            <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
              No raw sequence dataset.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
              {sequences.map((sequence) => (
                <button
                  key={sequence.sequence_id}
                  type="button"
                  onClick={() => setSelected(sequence)}
                  className={`group overflow-hidden rounded-md border bg-slate-50 text-left ${
                    selected?.sequence_id === sequence.sequence_id ? "border-blue-500 ring-2 ring-blue-100" : "border-slate-200"
                  }`}
                >
                  {thumbs[sequence.sequence_id] ? (
                    <img
                      src={thumbs[sequence.sequence_id]}
                      alt={sequence.sequence_id}
                      className="h-28 w-full bg-black object-contain"
                    />
                  ) : (
                    <div className="h-28 w-full bg-slate-200" />
                  )}
                  <div className="space-y-1 px-2 py-2">
                    <div className="truncate text-xs font-semibold text-slate-800">{sequence.track_id}</div>
                    <div className="flex items-center justify-between gap-2 text-[11px] text-slate-500">
                      <span>K={sequence.frame_count}</span>
                      <span>{sequence.label?.primary_label ?? "RAW"}</span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        <aside className="sticky top-4 h-[calc(100vh-10rem)] overflow-hidden rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Tag className="h-4 w-4 text-blue-600" />
            Review Track
          </div>
          {selected ? (
            <div className="h-full space-y-4 overflow-y-auto pr-1">
              {previewUrl && (
                <img
                  src={previewUrl}
                  alt={selected.sequence_id}
                  className="h-56 w-full rounded-md border border-slate-200 bg-black object-contain"
                />
              )}
              <div className="space-y-2">
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, selected.frame_count - 1)}
                  value={Math.min(frameIndex, Math.max(0, selected.frame_count - 1))}
                  onChange={(event) => setFrameIndex(Number(event.target.value))}
                  className="w-full"
                />
                <div className="flex justify-between text-xs text-slate-500">
                  <span>Frame {Math.min(frameIndex + 1, selected.frame_count)}</span>
                  <span>K={selected.frame_count}</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <label className="block text-sm">
                  <span className="text-xs font-medium text-slate-500">Intent</span>
                  <select
                    value={labelDraft}
                    onChange={(event) => setLabelDraft(event.target.value)}
                    className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  >
                    {INTENT_LABELS.map((label) => (
                      <option key={label} value={label}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-sm">
                  <span className="text-xs font-medium text-slate-500">Direction</span>
                  <select
                    value={secondaryDraft}
                    onChange={(event) => setSecondaryDraft(event.target.value)}
                    disabled={labelDraft !== "CROSSING"}
                    className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-100"
                  >
                    <option value="crossing_right">right</option>
                    <option value="crossing_left">left</option>
                  </select>
                </label>
              </div>
              <button
                type="button"
                onClick={saveManualLabel}
                disabled={busy}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Tag className="h-4 w-4" />
                Save Label
              </button>

              <div className="space-y-2 text-sm">
                <Detail label="Sequence" value={selected.sequence_id} />
                <Detail label="Session" value={selected.session_id ?? "-"} />
                <Detail label="Track" value={selected.track_id ?? "-"} />
                <Detail label="Depth Valid" value={formatPercent(selected.depth_valid_ratio)} />
                <Detail label="Label" value={selected.label?.primary_label ?? "RAW"} />
                <Detail label="Source" value={selected.label?.label_source ?? "-"} />
                <Detail label="Agents" value={formatAgents(selected.label?.labeling_agents)} />
                <Detail label="Confidence" value={formatPercent(selected.label?.confidence)} />
                <Detail label="Review" value={selected.label?.review_status ?? "-"} />
              </div>
              <pre className="max-h-72 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
                {JSON.stringify(selected.label ?? selected.metadata, null, 2)}
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
      <div className="mt-1 truncate font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-3 py-2">
      <span className="text-slate-500">{label}</span>
      <span className="truncate font-medium text-slate-900">{value}</span>
    </div>
  );
}

function formatPercent(value?: number) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "-";
}

function formatCounts(values: Record<string, number>) {
  const entries = Object.entries(values).filter(([, count]) => count > 0);
  return entries.length ? entries.map(([label, count]) => `${label}:${count}`).join(", ") : "0";
}

function formatBytes(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatAgents(values?: Record<string, boolean>) {
  if (!values) return "-";
  const active = Object.entries(values)
    .filter(([, enabled]) => enabled)
    .map(([name]) => name.toUpperCase());
  return active.length ? active.join(" + ") : "-";
}
