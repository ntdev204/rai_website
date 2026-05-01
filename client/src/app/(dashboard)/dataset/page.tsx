"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchWithAuth } from "@/lib/api";
import { CheckCircle2, Database, Download, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

interface DatasetStatus {
  status: "idle" | "recording" | "stopped" | "discarded" | "unavailable";
  dataset_mode?: string | null;
  session_id?: string;
  frame_count?: number;
  bytes_total?: number;
  saved?: boolean;
  dataset_stage?: string;
  autolabeled?: boolean;
}

interface DatasetImage {
  index: number;
  file: string;
  frame_id?: number;
  track_id?: number | string;
  timestamp?: number;
  metadata: Record<string, unknown>;
}

interface DatasetImagesResponse {
  session_id?: string;
  count: number;
  images: DatasetImage[];
}

interface AutolabelResult {
  status?: string;
  train_dataset_dir?: string;
  report_path?: string;
  validation_status?: number | null;
  ready_for_phase2_training?: boolean;
  error?: string | null;
}

export default function DatasetPage() {
  const PAGE_SIZE = 50;
  const objectUrlsRef = useRef<string[]>([]);
  const [status, setStatus] = useState<DatasetStatus>({ status: "idle" });
  const [images, setImages] = useState<DatasetImage[]>([]);
  const [thumbs, setThumbs] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<DatasetImage | null>(null);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [autolabel, setAutolabel] = useState<AutolabelResult | null>(null);

  const clearThumbs = useCallback(() => {
    objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    objectUrlsRef.current = [];
    setThumbs({});
  }, []);

  const loadImages = useCallback(async (currentStatus?: DatasetStatus) => {
    const nextStatus =
      currentStatus ??
      (await fetchWithAuth("/api/datasets/collection").then((response) => response.json()));
    setStatus(nextStatus);

    if (nextStatus.status === "idle" || nextStatus.status === "recording") {
      clearThumbs();
      setImages([]);
      setSelected(null);
      return;
    }

    const response = await fetchWithAuth("/api/datasets/collection/images");
    const payload = (await response.json()) as DatasetImagesResponse;
    setImages(payload.images ?? []);
    setSelected((current) => current ?? payload.images?.[0] ?? null);
    setPage(1);

    clearThumbs();
    const visible = payload.images ?? [];
    const entries = await Promise.all(
      visible.map(async (image) => {
        const preview = await fetchWithAuth(`/api/datasets/collection/preview/${image.index}`);
        const url = URL.createObjectURL(await preview.blob());
        objectUrlsRef.current.push(url);
        return [image.index, url] as const;
      }),
    );
    setThumbs(Object.fromEntries(entries));
  }, [clearThumbs]);

  useEffect(() => {
    void Promise.resolve()
      .then(() => loadImages())
      .catch((error) => {
        setMessage(error instanceof Error ? error.message : "Cannot load dataset");
      });
    return () => clearThumbs();
  }, [clearThumbs, loadImages]);

  const deleteImage = async (image: DatasetImage) => {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetchWithAuth(`/api/datasets/collection/images/${image.index}`, {
        method: "DELETE",
      });
      const payload = (await response.json()) as DatasetImagesResponse;
      setImages(payload.images ?? []);
      setSelected(payload.images?.[0] ?? null);
      await loadImages();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot delete image");
    } finally {
      setBusy(false);
    }
  };

  const runAutolabel = async () => {
    setBusy(true);
    setMessage("");
    setAutolabel(null);
    try {
      const response = await fetchWithAuth("/api/datasets/collection/autolabel", {
        method: "POST",
      });
      const result = (await response.json()) as AutolabelResult;
      setAutolabel(result);
      setMessage(
        result.error
          ? `Auto label failed: ${result.error}`
          : "Auto label finished. Review ERRATIC and UNCERTAIN samples before training.",
      );
      const nextStatus = await fetchWithAuth("/api/datasets/collection").then((item) => item.json());
      setStatus(nextStatus);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot run auto label");
    } finally {
      setBusy(false);
    }
  };

  const downloadDataset = async () => {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetchWithAuth("/api/datasets/collection/download");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const match = disposition.match(/filename="?([^"]+)"?/);
      const link = document.createElement("a");
      link.href = url;
      link.download = match?.[1] ?? "context_aware_dataset.zip";
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

  const totalPages = Math.max(1, Math.ceil(images.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const pageImages = images.slice(pageStart, pageStart + PAGE_SIZE);

  const canAutolabel = status.status === "stopped" && images.length > 0 && !busy;
  const canDownload = status.status === "stopped" && Boolean(status.autolabeled) && !busy;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-800">Dataset</h2>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => loadImages()}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            type="button"
            onClick={runAutolabel}
            disabled={!canAutolabel}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            Auto label
          </button>
          <button
            type="button"
            onClick={downloadDataset}
            disabled={!canDownload}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            Download
          </button>
        </div>
      </div>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <Metric label="Session" value={status.session_id ?? "-"} />
        <Metric label="Status" value={status.status} />
        <Metric label="Raw Images" value={String(images.length)} />
        <Metric label="Stage" value={status.dataset_stage ?? (status.saved ? "raw_review" : "-")} />
      </section>

      {message && (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
          {message}
        </div>
      )}

      {autolabel && (
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            Auto Label Result
          </div>
          <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
            <Metric label="Validation" value={String(autolabel.validation_status ?? "-")} />
            <Metric label="Phase 2 Ready" value={autolabel.ready_for_phase2_training ? "yes" : "no"} />
            <Metric label="Train Dataset" value={autolabel.train_dataset_dir ?? "-"} />
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_360px]">
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <Database className="h-4 w-4 text-indigo-600" />
              Raw ROI Preview
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                disabled={currentPage <= 1}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Prev
              </button>
              <span className="text-xs text-slate-600">
                Page {currentPage}/{totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                disabled={currentPage >= totalPages}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
              </button>
              <StatusBadge status={status.status === "stopped" ? "success" : "default"}>
                {images.length} images
              </StatusBadge>
            </div>
          </div>

          {images.length === 0 ? (
            <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
              No saved raw ROI session.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
              {pageImages.map((image) => (
                <button
                  key={`${image.index}-${image.file}`}
                  type="button"
                  onClick={() => setSelected(image)}
                  className={`group overflow-hidden rounded-md border bg-slate-50 text-left ${
                    selected?.index === image.index ? "border-blue-500 ring-2 ring-blue-100" : "border-slate-200"
                  }`}
                >
                  {thumbs[image.index] ? (
                    <img
                      src={thumbs[image.index]}
                      alt={image.file}
                      className="h-28 w-full bg-black object-contain"
                    />
                  ) : (
                    <div className="h-28 w-full bg-slate-200" />
                  )}
                  <div className="truncate px-2 py-1 text-xs text-slate-600">{image.file}</div>
                </button>
              ))}
            </div>
          )}
        </section>

        <aside className="sticky top-4 h-[calc(100vh-10rem)] overflow-hidden rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 text-sm font-semibold text-slate-800">Selected Image</div>
          {selected ? (
            <div className="h-full space-y-4 overflow-y-auto pr-1">
              {thumbs[selected.index] && (
                <img
                  src={thumbs[selected.index]}
                  alt={selected.file}
                  className="h-56 w-full rounded-md border border-slate-200 bg-black object-contain"
                />
              )}
              <div className="space-y-2 text-sm">
                <Detail label="File" value={selected.file} />
                <Detail label="Frame" value={String(selected.frame_id ?? "-")} />
                <Detail label="Track" value={String(selected.track_id ?? "-")} />
              </div>
              <button
                type="button"
                onClick={() => deleteImage(selected)}
                disabled={busy || status.status === "recording"}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-rose-200 bg-white px-3 py-2 text-sm font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
                Delete image and metadata
              </button>
              <pre className="max-h-72 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">
                {JSON.stringify(selected.metadata, null, 2)}
              </pre>
            </div>
          ) : (
            <div className="text-sm text-slate-500">Select an image to inspect metadata.</div>
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
