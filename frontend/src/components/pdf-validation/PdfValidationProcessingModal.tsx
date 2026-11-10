"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FileSearch, Loader2 } from "lucide-react";

interface Props {
  active?: boolean;
  filename?: string;
  fileNumber?: number;
  fileCount?: number;
  discovering: boolean;
  onCancel: () => void;
}

export function PdfValidationProcessingModal({ active = true, filename, fileNumber, fileCount, discovering, onCancel }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!active) return;
    const previous = document.activeElement as HTMLElement | null;
    const modal = dialog.current;
    modal?.showModal();
    return () => {
      modal?.close();
      if (previous?.isConnected && previous.getClientRects().length) previous.focus();
    };
  }, [active]);

  return createPortal(
    <dialog
      ref={dialog}
      hidden={!active}
      aria-labelledby="pdf-processing-title"
      aria-describedby="pdf-processing-description"
      aria-modal="true"
      onCancel={(event) => { event.preventDefault(); onCancel(); }}
      onKeyDown={(event) => {
        if (event.key === "Tab") {
          event.preventDefault();
          event.currentTarget.querySelector("button")?.focus();
        }
      }}
      className="m-auto max-h-[calc(100%-2rem)] w-[calc(100%-2rem)] max-w-md overflow-y-auto rounded-3xl border border-slate-200 bg-white p-6 text-slate-800 shadow-2xl backdrop:bg-slate-950/60 backdrop:backdrop-blur-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
    >
      <div className="relative mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-sky-50 text-sky-600 dark:bg-sky-950 dark:text-sky-300">
        <FileSearch className="h-7 w-7" aria-hidden="true" />
        <Loader2 className="absolute -bottom-1 -right-1 h-6 w-6 animate-spin rounded-full bg-white dark:bg-slate-900" aria-hidden="true" />
      </div>
      <h2 id="pdf-processing-title" className="text-center text-lg font-bold">
        {discovering ? "Finding published documents" : "Validating PDF"}
      </h2>
      {filename && !discovering && <p className="mt-2 truncate text-center text-sm font-medium" title={filename}>{filename}</p>}
      {!discovering && fileCount && fileNumber && <p role="status" className="mt-2 text-center text-sm font-semibold text-sky-700 dark:text-sky-300">
        PDF {fileNumber} of {fileCount}
      </p>}
      <p id="pdf-processing-description" role="status" className="mt-3 text-center text-sm text-slate-500 dark:text-slate-400">
        {discovering ? "Searching the website for PDF documents and ZIP downloads."
          : "Retrieving the source and comparing your PDF. Files are processed one at a time in selection order."}
      </p>
      <div role="progressbar" aria-label={discovering ? "PDF discovery progress" : "PDF validation progress"}
        className="mt-5 h-1.5 animate-pulse rounded-full bg-gradient-to-r from-sky-200 via-sky-500 to-indigo-500 motion-reduce:animate-none" />
      <p className="mt-3 text-center text-xs text-slate-500 dark:text-slate-400">
        Elapsed: {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
      </p>
      <p className="mt-4 text-center text-xs text-slate-500 dark:text-slate-400">
        {discovering ? "Available documents will appear when the search finishes." : "Results will appear when the queue finishes. Cancelling keeps completed results."}
      </p>
      <button type="button" onClick={onCancel}
        className="mt-5 w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">
        Cancel request
      </button>
    </dialog>,
    document.body
  );
}
