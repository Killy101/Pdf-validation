"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, Download, Loader2 } from "lucide-react";
import type { PdfValidationResult } from "@/lib/pdfValidation";
import { pdfLanguageName } from "@/lib/pdfLanguage";
import { fetchValidationPdf, pdfDownloadAvailability, pdfDownloadFilename, PdfDownloadKind } from "@/lib/pdfValidationDownloads";

// Header button that opens a small panel with the official and updated PDF downloads.
export function PdfValidationDownloads({result, file}: {result: PdfValidationResult; file?: File}) {
  const [busy, setBusy] = useState<PdfDownloadKind | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [open, setOpen] = useState(false);
  const request = useRef<AbortController | null>(null);
  const root = useRef<HTMLDivElement | null>(null);
  const panelId = useId();
  const available = pdfDownloadAvailability(result, Boolean(file));
  useEffect(() => () => request.current?.abort(), []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function download(kind: PdfDownloadKind) {
    const controller = new AbortController();
    request.current = controller;
    setBusy(kind);
    setError("");
    setMessage("");
    try {
      const blob = await fetchValidationPdf(result, kind, file, controller.signal);
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = pdfDownloadFilename(result, kind);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      setMessage(`${kind === "official" ? "Official" : "Updated"} PDF download started.`);
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(failure instanceof Error ? failure.message : "The PDF could not be downloaded.");
        setOpen(true);
      }
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  if (result.comparison === "not_checked" || !result.source_sha256) return null;
  return <div ref={root} className="relative">
    <button type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(value => !value)}
      className="inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 shadow-2xs transition-all hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700">
      {busy ? <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" /> : <Download aria-hidden="true" className="h-3.5 w-3.5 text-sky-600 dark:text-sky-400" />}
      <span>Download documents</span>
      <ChevronDown aria-hidden="true" className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
    </button>
    {open && <section id={panelId} aria-label="PDF downloads"
      className="absolute right-0 top-full z-30 mt-2 w-[22rem] max-w-[90vw] space-y-3 rounded-xl border border-slate-200 bg-white p-3 text-sm shadow-xl dark:border-slate-700 dark:bg-slate-900">
      <div className="flex flex-col gap-2">
        {(["official", "updated"] as const).map(kind => <button key={kind} type="button" onClick={() => void download(kind)}
          disabled={Boolean(busy) || !available[kind]}
          className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-100 dark:hover:bg-slate-800">
          {busy === kind ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <Download aria-hidden="true" className="h-4 w-4" />}
          {busy === kind ? (kind === "updated" ? "Generating PDF..." : "Downloading PDF...") : `Download ${kind === "official" ? "official" : "updated"} PDF`}
        </button>)}
      </div>
      <p className="text-xs leading-5 text-slate-600 dark:text-slate-400">The official PDF preserves the original published document. The updated PDF rebuilds the complete extracted source text in a clean layout with source details. Images and original table formatting are not reproduced.</p>
      {result.comparison_language === "en" && <p className="text-xs leading-5 text-slate-600 dark:text-slate-400">The updated PDF follows the English comparison scope. The official PDF retains both published language columns.</p>}
      {result.comparison_language && !["en", "all"].includes(result.comparison_language) && <p className="text-xs leading-5 text-slate-600 dark:text-slate-400">The updated PDF follows the {pdfLanguageName(result.comparison_language)} comparison scope. The official PDF retains the published document.</p>}
      {!available.official && <p className="text-xs text-slate-600 dark:text-slate-400">An official PDF download is available when the selected source is a PDF.</p>}
      {!available.updated && <p className="text-xs text-slate-600 dark:text-slate-400">Generating an updated PDF requires a confirmed document identity, complete text coverage, and the uploaded file.</p>}
      {error && <p role="alert" className="text-sm text-amber-800 dark:text-amber-300">{error}</p>}
      {message && <p role="status" className="text-sm text-slate-700 dark:text-slate-300">{message}</p>}
    </section>}
  </div>;
}
