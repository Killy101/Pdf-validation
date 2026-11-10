"use client";

import React, { useMemo, useState } from "react";
import {
  Check,
  Columns,
  Copy,
  ExternalLink,
  FileText,
  Rows,
  Sparkles,
  X
} from "lucide-react";
import { PdfFinding } from "@/lib/pdfValidation";
import { computeWordDiff, DiffPart } from "@/lib/pdfDiffUtils";
import { findingPageLabel, findingPdfPages } from "@/lib/pdfFindingLocation";

interface Props {
  finding: PdfFinding;
  onJumpToPdfPage?: (page: number) => void;
}

export function PdfFindingDiffInspector({ finding, onJumpToPdfPage }: Props) {
  const [viewMode, setViewMode] = useState<"diff" | "inline" | "plain">("diff");
  const [layoutMode, setLayoutMode] = useState<"stacked" | "side">("stacked");
  const [copiedTarget, setCopiedTarget] = useState<string | null>(null);
  const pdfPages = findingPdfPages(finding);

  // Compute word differences between expected and actual text.
  const diffResult = useMemo(() => {
    return computeWordDiff(finding.expected, finding.actual, finding.expected_change, finding.actual_change);
  }, [finding.expected, finding.actual, finding.expected_change, finding.actual_change]);

  const changeBadge = useMemo(() => {
    switch (finding.kind) {
      case "changed_content":
        return { label: "Modified from website", color: "bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 border-amber-200 dark:border-amber-800" };
      case "missing_content":
        return { label: "Missing from uploaded PDF", color: "bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 border-rose-200 dark:border-rose-800" };
      case "extra_content":
        return { label: "Extra in uploaded PDF", color: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800" };
      case "page_count":
        return { label: "Page count difference", color: "bg-purple-100 text-purple-800 dark:bg-purple-950/80 dark:text-purple-300 border-purple-200 dark:border-purple-800" };
      default:
        return { label: "Website difference", color: "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200 border-slate-200 dark:border-slate-700" };
    }
  }, [finding.kind]);

  async function handleCopy(text: string, targetKey: string) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedTarget(targetKey);
      setTimeout(() => setCopiedTarget(null), 2000);
    } catch {
      // Ignore clipboard write failures.
    }
  }

  function handleCopyDiffMarkdown() {
    const md = [
      `### Validation Finding (${finding.severity.toUpperCase()})`,
      finding.message,
      "",
      `**Source Heading/Page:** ${finding.source_heading || `Page ${finding.source_page || "N/A"}`}`,
      ...(finding.source_archive_member ? [`**Document inside ZIP:** ${finding.source_archive_member}`] : []),
      `**PDF location:** ${findingPageLabel(finding)}`,
      "",
      "**Expected from Website:**",
      "```",
      finding.expected || "(empty)",
      "```",
      "",
      "**Uploaded PDF Text:**",
      "```",
      finding.actual || "(empty)",
      "```",
    ].join("\n");
    handleCopy(md, "diff-md");
  }

  return (
    <div className="space-y-3 border-t border-slate-200 pt-3 dark:border-slate-800 animate-in fade-in duration-150">
      <div className="space-y-2 rounded-xl border border-sky-200 bg-sky-50/60 p-3 text-sm dark:border-sky-900 dark:bg-sky-950/30">
        <p className="font-semibold text-sky-950 dark:text-sky-100">{findingPageLabel(finding)}</p>
        {finding.source_archive_member && <p className="break-words text-xs">Document inside ZIP: {finding.source_archive_member}</p>}
        {finding.approximate_location && <p className="text-xs text-slate-600 dark:text-slate-300">This source text is absent from the upload. The page link opens nearby text for review.</p>}
        {finding.pdf_search_text && <div className="space-y-1 border-t border-sky-200 pt-2 dark:border-sky-900">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-semibold">{finding.approximate_location ? "Nearby text in your PDF" : "Find this text in your PDF"}</span>
            <button type="button" onClick={() => handleCopy(finding.pdf_search_text!, "search")}
              className="font-semibold text-sky-700 underline dark:text-sky-300">{copiedTarget === "search" ? "Copied!" : "Copy search text"}</button>
          </div>
          <p className="break-words leading-relaxed text-slate-800 dark:text-slate-200">{finding.pdf_search_text}</p>
          <p className="text-xs text-slate-500">Open the page and use Ctrl+F (Command+F on Mac) to find the copied text.</p>
        </div>}
      </div>
      {/* Website Context Header with Source Link, Target Page, and Controls */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <a
            href={finding.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="break-words text-xs sm:text-sm text-sky-700 underline dark:text-sky-300 inline-flex items-center gap-1 font-semibold hover:text-sky-800"
          >
            <span>
              {finding.source_heading || (finding.source_page ? `Source page ${finding.source_page}` : "Open source location")}
            </span>
            <ExternalLink className="h-3 w-3 shrink-0" />
          </a>

          <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${changeBadge.color}`}>
            {changeBadge.label}
          </span>

          {finding.pdf_page != null && (
            <button
              type="button"
              onClick={() => onJumpToPdfPage?.(finding.pdf_page!)}
              title={`View Page ${finding.pdf_page} in preview`}
              className="inline-flex items-center gap-1 rounded-md bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 px-2 py-0.5 text-[11px] font-mono font-bold text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 cursor-pointer"
            >
              <span>{finding.approximate_location ? "Near uploaded page" : "Uploaded page"} {finding.pdf_page}</span>
            </button>
          )}
        </div>

        {/* Diff Mode and Layout Controls */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {/* Diff Mode Toggle: Diff Highlight vs Inline vs Plain */}
          <div className="flex items-center rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-[11px] font-semibold dark:border-slate-700 dark:bg-slate-800">
            <button
              type="button"
              onClick={() => setViewMode("diff")}
              className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 transition-all cursor-pointer ${
                viewMode === "diff"
                  ? "bg-white text-sky-700 shadow-2xs dark:bg-slate-700 dark:text-sky-300"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              <Sparkles className="h-3 w-3" />
              <span>Diff Highlight</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode("inline")}
              className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 transition-all cursor-pointer ${
                viewMode === "inline"
                  ? "bg-white text-sky-700 shadow-2xs dark:bg-slate-700 dark:text-sky-300"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              <span>Inline</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode("plain")}
              className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 transition-all cursor-pointer ${
                viewMode === "plain"
                  ? "bg-white text-slate-800 shadow-2xs dark:bg-slate-700 dark:text-slate-200"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              <FileText className="h-3 w-3" />
              <span>Plain</span>
            </button>
          </div>

          {/* Layout Mode Toggle: Stacked vs Side-by-Side (Active in diff or plain) */}
          {viewMode !== "inline" && (
            <div className="flex items-center rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-[11px] font-semibold dark:border-slate-700 dark:bg-slate-800">
              <button
                type="button"
                onClick={() => setLayoutMode("stacked")}
                title="Stacked view"
                className={`rounded-md p-1 transition-all cursor-pointer ${
                  layoutMode === "stacked"
                    ? "bg-white text-sky-700 shadow-2xs dark:bg-slate-700 dark:text-sky-300"
                    : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                <Rows className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setLayoutMode("side")}
                title="Side-by-side view"
                className={`rounded-md p-1 transition-all cursor-pointer ${
                  layoutMode === "side"
                    ? "bg-white text-sky-700 shadow-2xs dark:bg-slate-700 dark:text-sky-300"
                    : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                <Columns className="h-3.5 w-3.5" />
              </button>
            </div>
          )}

          {/* Copy Full Finding Button */}
          <button
            type="button"
            onClick={handleCopyDiffMarkdown}
            title="Copy finding details"
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 shadow-2xs hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 cursor-pointer"
          >
            {copiedTarget === "diff-md" ? (
              <>
                <Check className="h-3 w-3 text-emerald-600" />
                <span className="text-emerald-700 dark:text-emerald-300 font-bold">Copied!</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Difference Stats Chip with Legend */}
      {diffResult.hasDifferences && (
        <div className="flex items-center gap-2 text-[11px] text-slate-500 flex-wrap">
          <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 font-bold font-mono text-amber-700 border border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900/60">
            {diffResult.changesCount} highlighted word difference{diffResult.changesCount === 1 ? "" : "s"}
          </span>
          <span className="text-slate-500">
            Red: source wording. Green: uploaded wording.
          </span>
        </div>
      )}
      {finding.excerpt_truncated && <p className="text-xs text-slate-600 dark:text-slate-300">Showing an excerpt. Review the full PDF pages listed above.</p>}

      {/* Unified Inline View or Side-by-Side/Stacked Comparison */}
      {viewMode === "inline" ? (
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <h3 className="text-[11px] font-semibold uppercase text-slate-500 flex items-center gap-1">
              <Sparkles className="h-3 w-3 text-sky-600" />
              <span>Unified Comparison (Website text with PDF changes)</span>
            </h3>
            <button
              type="button"
              onClick={() => handleCopy(diffResult.unifiedParts.map((p) => p.value).join(""), "inline")}
              className="text-[10px] font-medium text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 cursor-pointer"
            >
              {copiedTarget === "inline" ? "Copied!" : "Copy text"}
            </button>
          </div>
          <div className="whitespace-pre-wrap break-words rounded-xl bg-slate-50/80 p-4 text-sm dark:bg-slate-900/60 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-800 max-h-96 overflow-y-auto leading-7">
            {diffResult.unifiedParts.length > 0 ? (
              diffResult.unifiedParts.map((part: DiffPart, index: number) => {
                if (part.type === "removed") {
                  return (
                    <mark
                      key={index}
                      title="Missing from uploaded PDF (present on website)"
                      className="rounded-sm bg-rose-100/80 text-rose-600 dark:bg-rose-950/60 dark:text-rose-300 font-medium"
                    >
                      {part.value}
                    </mark>
                  );
                }
                if (part.type === "added") {
                  return (
                    <mark
                      key={index}
                      title="Altered or added in uploaded PDF"
                      className="rounded-sm bg-emerald-200/80 text-emerald-950 dark:bg-emerald-950/90 dark:text-emerald-200 font-medium"
                    >
                      {part.value}
                    </mark>
                  );
                }
                return <span key={index}>{part.value}</span>;
              })
            ) : (
              <span>No diff available.</span>
            )}
          </div>
        </div>
      ) : (
        <div className={layoutMode === "side" ? "grid grid-cols-1 sm:grid-cols-2 gap-3" : "space-y-2.5"}>
          {/* Expected from Website Block */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <h3 className="text-[11px] font-semibold uppercase text-slate-500 flex items-center gap-1">
              <Check className="h-3 w-3 text-emerald-600" />
              <span>Expected from website</span>
            </h3>
            <button
              type="button"
              onClick={() => handleCopy(finding.expected, "expected")}
              className="text-[10px] font-medium text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 cursor-pointer"
            >
              {copiedTarget === "expected" ? "Copied!" : "Copy text"}
            </button>
          </div>
          <div role="region" aria-label="Source text excerpt" className="whitespace-pre-wrap break-words rounded-xl bg-white p-4 text-sm dark:bg-slate-900 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 max-h-96 overflow-y-auto leading-7">
            {viewMode === "diff" && diffResult.expectedParts.length > 0 ? (
              diffResult.expectedParts.map((part: DiffPart, index: number) => {
                if (part.type === "removed") {
                  return (
                    <mark
                      key={index}
                      className="rounded-sm bg-rose-100/80 text-rose-600 dark:bg-rose-950/60 dark:text-rose-300 font-medium"
                    >
                      {part.value}
                    </mark>
                  );
                }
                return <span key={index}>{part.value}</span>;
              })
            ) : (
              <span>{finding.expected || "No corresponding text in the selected source."}</span>
            )}
          </div>
        </div>

        {/* Uploaded PDF Block */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <h3 className="text-[11px] font-semibold uppercase text-slate-500 flex items-center gap-1">
              <X className="h-3 w-3 text-rose-600" />
              <span>Uploaded PDF</span>
            </h3>
            <button
              type="button"
              onClick={() => handleCopy(finding.actual, "actual")}
              className="text-[10px] font-medium text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 cursor-pointer"
            >
              {copiedTarget === "actual" ? "Copied!" : "Copy text"}
            </button>
          </div>
          <div role="region" aria-label="Uploaded PDF text excerpt" className="whitespace-pre-wrap break-words rounded-xl bg-white p-4 text-sm dark:bg-slate-900 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 max-h-96 overflow-y-auto leading-7">
            {viewMode === "diff" && diffResult.actualParts.length > 0 ? (
              diffResult.actualParts.map((part: DiffPart, index: number) => {
                if (part.type === "added") {
                  return (
                    <mark
                      key={index}
                      className="rounded-sm bg-emerald-200/80 text-emerald-950 dark:bg-emerald-950/90 dark:text-emerald-200 font-medium"
                    >
                      {part.value}
                    </mark>
                  );
                }
                return <span key={index}>{part.value}</span>;
              })
            ) : (
              <span>{finding.actual || "No corresponding text was found in the PDF."}</span>
            )}
          </div>
        </div>
      </div>
      )}

      {/* Suggested Action Note */}
      {finding.action && (
        <p className="text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 p-2 rounded-xl border border-slate-100 dark:border-slate-700/60">
          <span className="font-semibold text-slate-700 dark:text-slate-300">Action: </span>
          {finding.action}
        </p>
      )}
    </div>
  );
}
