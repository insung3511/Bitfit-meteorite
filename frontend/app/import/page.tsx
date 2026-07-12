"use client";

import { useRef, useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type ImportSummary = {
  rows_inserted: Record<string, number>;
  rows_inserted_total: number;
  rows_skipped_existing: number;
  files_processed: number;
  files_skipped: number;
  files_errored: number;
  errors: { file: string; error: string }[];
};

type ImportState =
  | { status: "idle" }
  | { status: "uploading" }
  | { status: "done"; summary: ImportSummary }
  | { status: "error"; message: string };

export default function ImportPage() {
  const [state, setState] = useState<ImportState>({ status: "idle" });
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setState({
        status: "error",
        message: "Please choose a Google Takeout .zip file.",
      });
      return;
    }

    setState({ status: "uploading" });
    const body = new FormData();
    body.append("file", file);

    try {
      const response = await fetch(`${API_BASE_URL}/import/takeout`, {
        method: "POST",
        credentials: "include",
        body,
      });
      if (!response.ok) {
        const detail = await response
          .json()
          .then((value: { detail?: string }) => value.detail)
          .catch(() => null);
        setState({
          status: "error",
          message: detail ?? `Import failed (${response.status}).`,
        });
        return;
      }
      setState({
        status: "done",
        summary: (await response.json()) as ImportSummary,
      });
    } catch {
      setState({
        status: "error",
        message: `Could not reach the backend at ${API_BASE_URL}.`,
      });
    }
  }

  function onDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const file = event.dataTransfer.files.item(0);
    if (file) void upload(file);
  }

  const uploading = state.status === "uploading";

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold">Import health data</h1>
        <p className="mt-1 max-w-2xl text-sm text-black/60 dark:text-white/60">
          Upload your Google Takeout export to load historical Fitbit or Google
          Fit data. Re-importing the same export is safe; existing rows are
          skipped.
        </p>
      </div>

      <div
        role="button"
        tabIndex={uploading ? -1 : 0}
        aria-disabled={uploading}
        onClick={() => !uploading && inputRef.current?.click()}
        onKeyDown={(event) => {
          if (!uploading && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!uploading) setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={uploading ? (event) => event.preventDefault() : onDrop}
        className={`flex min-h-52 flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          uploading ? "cursor-wait opacity-70" : "cursor-pointer"
        } ${
          dragActive
            ? "border-black/60 bg-black/5 dark:border-white/60 dark:bg-white/10"
            : "border-black/20 dark:border-white/25"
        }`}
      >
        <p className="text-sm font-medium">
          Drop your Google Takeout .zip here or click to browse
        </p>
        <p className="mt-2 text-xs text-black/45 dark:text-white/45">
          {uploading
            ? "Importing… this can take a moment for large exports."
            : "Export at takeout.google.com, select Fitbit, then upload the .zip."}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".zip,application/zip"
          disabled={uploading}
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.item(0);
            if (file) void upload(file);
            event.target.value = "";
          }}
        />
      </div>

      {state.status === "error" && (
        <div
          role="alert"
          className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-700 dark:text-red-300"
        >
          {state.message}
        </div>
      )}

      {state.status === "done" && (
        <section className="rounded-xl border border-black/10 p-4 dark:border-white/15">
          <h2 className="mb-3 text-sm font-medium">Import complete</h2>
          <ul className="space-y-1 text-sm">
            <li>
              Rows imported: <strong>{state.summary.rows_inserted_total}</strong>
            </li>
            <li>Already imported: {state.summary.rows_skipped_existing}</li>
            <li>
              Files: {state.summary.files_processed} processed, {" "}
              {state.summary.files_skipped} skipped, {" "}
              {state.summary.files_errored} errored
            </li>
          </ul>

          {Object.keys(state.summary.rows_inserted).length > 0 && (
            <div className="mt-3">
              <div className="text-[11px] uppercase tracking-wide text-black/40 dark:text-white/40">
                By metric
              </div>
              <ul className="mt-1 grid grid-cols-2 gap-x-6 text-sm">
                {Object.entries(state.summary.rows_inserted).map(
                  ([metric, count]) => (
                    <li key={metric} className="flex justify-between">
                      <span>{metric}</span>
                      <span className="font-mono">{count}</span>
                    </li>
                  ),
                )}
              </ul>
            </div>
          )}

          {state.summary.errors.length > 0 && (
            <div className="mt-3 text-sm text-amber-700 dark:text-amber-300">
              {state.summary.errors.length} file error(s) were reported during
              import.
            </div>
          )}

          <a
            href="/dashboard"
            className="mt-4 inline-block rounded-md bg-black px-3 py-1.5 text-xs font-medium text-white dark:bg-white dark:text-black"
          >
            View dashboard
          </a>
        </section>
      )}
    </div>
  );
}
