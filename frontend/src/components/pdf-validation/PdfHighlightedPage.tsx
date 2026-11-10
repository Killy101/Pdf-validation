"use client";

import React, { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { HighlightBox as Box, highlightBoxes, PositionedPiece } from "@/lib/pdfTextHighlights";

type PdfJs = typeof import("pdfjs-dist");
let library: Promise<PdfJs> | null = null;

function pdfjs() {
  library ??= import("pdfjs-dist").then(module => {
    // Copied to public/ by the copy:pdf-worker script; bundling it breaks the Next.js minifier.
    module.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
    return module;
  });
  return library;
}

// One open document per uploaded file, so stepping through matches does not parse the PDF again.
const documents = new WeakMap<File, Promise<PDFDocumentProxy>>();

function open(file: File) {
  let document = documents.get(file);
  if (!document) {
    document = Promise.all([pdfjs(), file.arrayBuffer()]).then(([module, data]) =>
      module.getDocument({ data: new Uint8Array(data), isEvalSupported: false }).promise);
    documents.set(file, document);
  }
  return document;
}

interface Props { file: File; page: number; query: string; className?: string; onMatches?: (count: number) => void }

// Renders one page of the uploaded PDF and marks every occurrence of the search text on it.
export function PdfHighlightedPage({ file, page, query, className = "", onMatches }: Props) {
  const frame = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");

  useEffect(() => {
    let cancelled = false;
    let task: { cancel: () => void; promise: Promise<unknown> } | null = null;
    setState("loading");
    (async () => {
      const [module, document] = await Promise.all([pdfjs(), open(file)]);
      const pdfPage = await document.getPage(Math.min(Math.max(1, page), document.numPages));
      if (cancelled || !frame.current || !canvas.current) return;
      const natural = pdfPage.getViewport({ scale: 1 });
      const viewport = pdfPage.getViewport({ scale: Math.max(0.5, (frame.current.clientWidth - 24) / natural.width) });
      const ratio = window.devicePixelRatio || 1;
      canvas.current.width = Math.floor(viewport.width * ratio);
      canvas.current.height = Math.floor(viewport.height * ratio);
      const context = canvas.current.getContext("2d")!;
      task = pdfPage.render({ canvasContext: context, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] });
      const content = await pdfPage.getTextContent();
      await task.promise;
      if (cancelled) return;

      const pieces = content.items.filter((item): item is typeof item & PositionedPiece => "str" in item);
      const measure = window.document.createElement("canvas").getContext("2d")!;
      const found = highlightBoxes(pieces, content.styles, query, viewport, module.Util.transform, measure);
      setSize({ width: viewport.width, height: viewport.height });
      setBoxes(found);
      setState("ready");
      onMatches?.(new Set(found.map(box => box.match)).size);
    })().catch(error => {
      if (cancelled || (error as Error)?.name === "RenderingCancelledException") return;
      setState("failed");
    });
    return () => { cancelled = true; task?.cancel(); };
  }, [file, page, query, onMatches]);

  // Bring the first match on the page into view.
  useEffect(() => {
    if (state !== "ready" || !boxes.length || !frame.current) return;
    frame.current.scrollTo({ top: Math.max(0, boxes[0].top - 80), behavior: "smooth" });
  }, [state, boxes]);

  return (
    <div ref={frame} className={`relative overflow-auto rounded-xl border border-slate-200 bg-slate-100 p-3 dark:border-slate-700 dark:bg-slate-950 ${className}`}>
      {state === "loading" && (
        <div className="absolute inset-0 z-10 flex items-center justify-center gap-2 text-xs text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Rendering page {page}…
        </div>
      )}
      {state === "failed" && <p role="alert" className="p-4 text-xs text-rose-700 dark:text-rose-300">This page could not be rendered with highlights. Switch to the PDF viewer.</p>}
      <div className="relative mx-auto bg-white shadow" style={{ width: size.width || undefined, height: size.height || undefined }}>
        <canvas ref={canvas} aria-label={`Page ${page} of the uploaded PDF`} style={{ width: size.width || undefined, height: size.height || undefined, display: "block" }} />
        {boxes.map((box, index) => (
          <mark key={index} data-match={box.match} aria-hidden="true"
            className="pointer-events-none absolute rounded-sm bg-amber-300/50 ring-1 ring-amber-500/70 mix-blend-multiply"
            style={{ left: box.left, top: box.top, width: box.width, height: box.height }} />
        ))}
      </div>
    </div>
  );
}
