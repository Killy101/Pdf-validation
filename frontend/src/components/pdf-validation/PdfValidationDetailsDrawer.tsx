"use client";

import { useEffect, useRef, useState } from "react";
import { ExternalLink, Globe, X } from "lucide-react";
import { PDF_JURISDICTIONS, type PdfValidationResult } from "@/lib/pdfValidation";
import { PdfValidationEvidence } from "./PdfValidationEvidence";
import { PdfDiscoveryPath } from "./PdfDiscoveryTrail";

// Where the compared document came from: jurisdiction, identity, retrieval time and the source link.
export function PdfSourceDetails({result}: {result: PdfValidationResult}) {
  return <section aria-label="Source details" className="space-y-1 break-words rounded-xl border border-slate-100 bg-slate-50/70 p-3 text-xs sm:text-sm dark:border-slate-800 dark:bg-slate-800/40">
    {result.jurisdiction && <p><span className="text-slate-500">Jurisdiction: </span>{PDF_JURISDICTIONS[result.jurisdiction]}</p>}
    {result.source_mode === "reference" && <p><span className="text-slate-500">Reference URL: </span><span className="break-all">{result.submitted_url}</span></p>}
    {result.document_identity === "match" && <p><span className="text-slate-500">Document identity: </span>Same document</p>}
    {result.archive_source && <p><span className="text-slate-500">Document inside ZIP: </span><span className="font-semibold">{result.archive_source.member}</span></p>}
    {result.source_retrieved_at && <p><span className="text-slate-500">Source retrieved: </span>{new Date(result.source_retrieved_at).toLocaleString()}
      {(result.retrieval_attempts ?? 0) > 1 && ` (${result.retrieval_attempts} attempts)`}</p>}
    {result.source_title && <p><span className="text-slate-500">Source document: </span><span className="font-semibold text-slate-900 dark:text-slate-100">{result.source_title}</span></p>}
    <div className="flex min-w-0 items-center gap-1.5">
      <Globe className="h-3.5 w-3.5 shrink-0 text-sky-600" />
      <a href={result.source_url} target="_blank" rel="noopener noreferrer"
        className="inline-flex min-w-0 items-center gap-1 font-mono text-xs text-sky-700 underline hover:text-sky-800 sm:text-sm dark:text-sky-300">
        <span className="truncate">{result.source_url}</span>
        <ExternalLink className="h-3 w-3 shrink-0" />
      </a>
    </div>
  </section>;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function PdfValidationDetailsDrawer({result, open, onClose}: {result: PdfValidationResult; open: boolean; onClose: () => void}) {
  const [entered, setEntered] = useState(false);
  const panel = useRef<HTMLElement | null>(null);
  const closeButton = useRef<HTMLButtonElement | null>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    if (!open) {
      setEntered(false);
      return;
    }
    const frame = requestAnimationFrame(() => setEntered(true));
    closeButton.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        close.current();
        return;
      }
      if (event.key !== "Tab" || !panel.current) return;
      // Keep keyboard focus inside the drawer while it is open.
      const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!open) return null;
  return <div className="fixed inset-0 z-50 flex justify-end">
    <div aria-hidden="true" onClick={onClose}
      className={`absolute inset-0 bg-slate-900/40 transition-opacity duration-200 ${entered ? "opacity-100" : "opacity-0"}`} />
    <aside ref={panel} role="dialog" aria-modal="true" aria-labelledby="pdf-details-title"
      className={`relative flex h-full w-full max-w-xl flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform duration-200 ease-out sm:max-w-2xl dark:border-slate-700 dark:bg-slate-900 ${entered ? "translate-x-0" : "translate-x-full"}`}>
      <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <div className="min-w-0">
          <h2 id="pdf-details-title" className="text-base font-bold text-slate-900 dark:text-slate-100">Details</h2>
          <p className="truncate text-xs text-slate-500 dark:text-slate-400">{result.filename}</p>
        </div>
        <button ref={closeButton} type="button" onClick={onClose} aria-label="Close details"
          className="cursor-pointer rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100">
          <X className="h-4 w-4" />
        </button>
      </header>
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <PdfSourceDetails result={result} />
        {result.discovery && <PdfDiscoveryPath trail={result.discovery} />}
        <PdfValidationEvidence result={result} />
      </div>
    </aside>
  </div>;
}
