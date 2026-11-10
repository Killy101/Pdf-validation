"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Loader2,
  Maximize2,
  Minimize2,
  RotateCcw,
  Search,
  Sparkles,
  X
} from "lucide-react";
import { PdfFinding, PdfTextSearchResult, searchPdfText } from "@/lib/pdfValidation";
import { findingOnPdfPage, findingPdfPages } from "@/lib/pdfFindingLocation";

interface Props {
  active?: boolean;
  preview: string;
  page: number;
  filename?: string;
  file?: File | null;
  className: string;
  totalPages?: number | null;
  findings?: PdfFinding[];
  selectedFindingIndex?: number;
  onSelectFinding?: (index: number) => void;
  onPageChange?: (newPage: number) => void;
}

export function PdfValidationPreview({
  active = true,
  preview,
  page,
  filename,
  file,
  className,
  totalPages,
  findings,
  selectedFindingIndex,
  onSelectFinding,
  onPageChange
}: Props) {
  const [currentPage, setCurrentPage] = useState(page || 1);
  const [expanded, setExpanded] = useState(false);
  const issuePage = findings?.[selectedFindingIndex ?? 0]?.pdf_page ?? page;

  // Search inside the PDF text.
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchResult, setSearchResult] = useState<PdfTextSearchResult | null>(null);
  const [activeMatch, setActiveMatch] = useState(0);
  const searchAbort = useRef<AbortController | null>(null);

  function clearSearch() {
    searchAbort.current?.abort();
    setQuery("");
    setSearching(false);
    setSearchError("");
    setSearchResult(null);
    setActiveMatch(0);
  }

  // A different document invalidates earlier results; leaving the screen cancels a running search.
  useEffect(() => {
    clearSearch();
    return () => searchAbort.current?.abort();
  }, [file]);

  function showMatch(index: number) {
    const match = searchResult?.matches[index];
    if (!match) return;
    setActiveMatch(index);
    setCurrentPage(match.page);
    onPageChange?.(match.page);
  }

  async function runSearch() {
    const text = query.trim();
    if (!file || text.length < 2 || searching) return;
    searchAbort.current?.abort();
    const controller = new AbortController();
    searchAbort.current = controller;
    setSearching(true);
    setSearchError("");
    try {
      const found = await searchPdfText(file, text, controller.signal);
      if (controller.signal.aborted) return;
      setSearchResult(found);
      setActiveMatch(0);
      if (found.matches.length) {
        setCurrentPage(found.matches[0].page);
        onPageChange?.(found.matches[0].page);
        // The built-in viewer cannot be told what to highlight; its own Ctrl+F search can paste this.
        void navigator.clipboard?.writeText(text).catch(() => undefined);
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      setSearchResult(null);
      setSearchError(error instanceof Error ? error.message : "The PDF could not be searched.");
    } finally {
      if (searchAbort.current === controller) setSearching(false);
    }
  }

  // Synchronize internal page when finding page changes.
  useEffect(() => {
    setCurrentPage(page || 1);
  }, [page]);

  // Handle escape key to exit expanded mode.
  useEffect(() => {
    if (!active || !expanded) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && expanded) {
        setExpanded(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [active, expanded]);

  // Extract all distinct page numbers that have differences from the website.
  const changedPages = useMemo(() => {
    if (!findings || findings.length === 0) return [];
    const pages = new Set<number>();
    for (const item of findings) {
      findingPdfPages(item, totalPages ?? 2000).forEach(value => pages.add(value));
    }
    return Array.from(pages).sort((a, b) => a - b);
  }, [findings, totalPages]);

  // Findings for the current active page in the preview.
  const currentPageFindings = useMemo(() => {
    if (!findings) return [];
    return findings.filter((item) => findingOnPdfPage(item, currentPage));
  }, [findings, currentPage]);

  // Locate the previous changed page relative to the current preview position.
  const prevChangedPage = useMemo(() => {
    const previous = changedPages.filter((p) => p < currentPage);
    return previous.length > 0 ? previous[previous.length - 1] : null;
  }, [changedPages, currentPage]);

  // Locate the next changed page relative to the current preview position.
  const nextChangedPage = useMemo(() => {
    const next = changedPages.filter((p) => p > currentPage);
    return next.length > 0 ? next[0] : null;
  }, [changedPages, currentPage]);

  function handlePageStep(delta: number) {
    const maxP = totalPages && totalPages > 0 ? totalPages : Infinity;
    const nextPage = Math.min(Math.max(1, currentPage + delta), maxP);
    setCurrentPage(nextPage);
    onPageChange?.(nextPage);
  }

  function handleJumpToPage(targetPage: number) {
    const maxP = totalPages && totalPages > 0 ? totalPages : Infinity;
    const clamped = Math.min(Math.max(1, targetPage), maxP);
    setCurrentPage(clamped);
    onPageChange?.(clamped);
    if (findings && onSelectFinding) {
      const idx = findings.findIndex((f) => findingOnPdfPage(f, clamped));
      if (idx !== -1) {
        onSelectFinding(idx);
      }
    }
  }

  function handleReturnToIssuePage() {
    setCurrentPage(issuePage);
    onPageChange?.(issuePage);
  }

  function handleStepChange(direction: "prev" | "next") {
    const target = direction === "prev" ? prevChangedPage : nextChangedPage;
    if (target != null) {
      handleJumpToPage(target);
    }
  }

  return (
    <>
      <section id="uploaded-pdf-preview" className={`${className} min-w-0 space-y-2.5 flex flex-col scroll-mt-4`}>
        {/* Header with Title, Page Stepper and Expand controls */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <h2 className="text-sm sm:text-base font-semibold">Uploaded PDF preview</h2>
            {currentPage !== issuePage && issuePage > 0 && (
              <button
                type="button"
                onClick={handleReturnToIssuePage}
                title={`Return to issue on page ${issuePage}`}
                className="inline-flex items-center gap-1 rounded-lg bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-700 hover:bg-sky-100 dark:bg-sky-950/60 dark:text-sky-300 dark:hover:bg-sky-900/60 cursor-pointer"
              >
                <RotateCcw className="h-3 w-3" />
                <span>Jump to issue (p. {issuePage})</span>
              </button>
            )}
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            {/* Previous and Next Change Stepper */}
            {changedPages.length > 0 && (
              <div className="flex items-center rounded-lg border border-slate-200 bg-slate-50 p-0.5 dark:border-slate-700 dark:bg-slate-800 text-[11px]">
                <button
                  type="button"
                  aria-label="Previous changed page"
                  disabled={prevChangedPage === null}
                  onClick={() => handleStepChange("prev")}
                  title={prevChangedPage ? `Jump to previous change on Page ${prevChangedPage}` : "No previous changed page"}
                  className="rounded px-1.5 py-0.5 font-semibold text-slate-600 hover:bg-white disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer flex items-center gap-0.5"
                >
                  <ChevronLeft className="h-3 w-3" />
                  <span>Prev change</span>
                </button>
                <span className="text-slate-300 dark:text-slate-600">|</span>
                <button
                  type="button"
                  aria-label="Next changed page"
                  disabled={nextChangedPage === null}
                  onClick={() => handleStepChange("next")}
                  title={nextChangedPage ? `Jump to next change on Page ${nextChangedPage}` : "No next changed page"}
                  className="rounded px-1.5 py-0.5 font-semibold text-slate-600 hover:bg-white disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer flex items-center gap-0.5"
                >
                  <span>Next change</span>
                  <ChevronRight className="h-3 w-3" />
                </button>
              </div>
            )}

            {/* Interactive Page Stepper */}
            {preview && (
              <div className="flex items-center rounded-lg border border-slate-200 bg-slate-50 p-0.5 dark:border-slate-700 dark:bg-slate-800">
                <button
                  type="button"
                  aria-label="Previous PDF page"
                  disabled={currentPage <= 1}
                  onClick={() => handlePageStep(-1)}
                  className="rounded p-1 text-slate-600 hover:bg-white disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
                <span className="px-2 text-xs font-mono font-bold text-slate-700 dark:text-slate-200">
                  Page {currentPage}{totalPages ? ` of ${totalPages}` : ""}
                </span>
                <button
                  type="button"
                  aria-label="Next PDF page"
                  disabled={totalPages ? currentPage >= totalPages : false}
                  onClick={() => handlePageStep(1)}
                  className="rounded p-1 text-slate-600 hover:bg-white disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer"
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            )}

            {!preview && (
              <span className="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-mono font-bold text-slate-500 dark:bg-slate-800">
                Page {page}
              </span>
            )}

            {/* Open in new browser tab button */}
            {preview && (
              <a
                href={`${preview}#page=${currentPage}`}
                target="_blank"
                rel="noopener noreferrer"
                title="Open in new browser tab"
                className="inline-flex items-center justify-center rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800 cursor-pointer"
              >
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}

            {/* Fullscreen Expand Button */}
            {preview && (
              <button
                type="button"
                onClick={() => setExpanded(true)}
                title="Expand preview"
                className="inline-flex items-center justify-center rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800 cursor-pointer"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Active Page Change Status Callout Banner */}
        {findings && findings.length > 0 && (
          <div className="min-w-0">
            {currentPageFindings.length > 0 ? (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-200/80 bg-rose-50/70 p-2 sm:px-3 text-xs dark:border-rose-900/50 dark:bg-rose-950/30">
                <div className="flex items-center gap-2 min-w-0">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-rose-600 dark:text-rose-400" />
                  <div className="min-w-0 truncate">
                    <span className="font-bold text-rose-900 dark:text-rose-200">
                      Page {currentPage} has {currentPageFindings.length} change{currentPageFindings.length === 1 ? "" : "s"} from website:
                    </span>{" "}
                    <span className="text-slate-700 dark:text-slate-300">
                      {currentPageFindings[0].message}
                    </span>
                    {currentPageFindings[0].source_heading && (
                      <span className="ml-1 text-[11px] text-slate-500 dark:text-slate-400 italic">
                        ({currentPageFindings[0].source_heading})
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-2 rounded-xl border border-emerald-200/80 bg-emerald-50/60 p-2 sm:px-3 text-xs dark:border-emerald-900/50 dark:bg-emerald-950/30">
                <div className="flex items-center gap-2 min-w-0">
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                  <span className="text-emerald-900 dark:text-emerald-200 font-medium">
                    No reported finding on uploaded page {currentPage}. Check coverage before accepting.
                  </span>
                </div>
                {nextChangedPage && (
                  <button
                    type="button"
                    onClick={() => handleJumpToPage(nextChangedPage)}
                    className="text-[11px] font-semibold text-sky-700 dark:text-sky-300 hover:underline cursor-pointer"
                  >
                    Next change: Page {nextChangedPage} →
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {filename && (
          <p className="truncate text-xs font-medium text-slate-500" title={filename}>
            {filename}
          </p>
        )}

        {preview && <form className="flex flex-wrap items-center gap-2 text-xs" onSubmit={event => {
          event.preventDefault();
          const input = event.currentTarget.elements.namedItem("pdfPage") as HTMLInputElement;
          const target = Number(input.value);
          if (Number.isInteger(target) && target > 0) handleJumpToPage(target);
        }}>
          <label htmlFor="pdf-preview-page" className="font-semibold">Go to uploaded page</label>
          <input key={currentPage} id="pdf-preview-page" name="pdfPage" type="number" min={1} max={totalPages ?? undefined}
            defaultValue={currentPage} className="w-20 rounded-lg border border-slate-300 bg-white px-2 py-1 dark:border-slate-700 dark:bg-slate-900" />
          <button type="submit" className="rounded-lg border border-sky-200 px-3 py-1 font-semibold text-sky-700 dark:border-sky-800 dark:text-sky-300">Go</button>
        </form>}

        {/* Search the text of the uploaded PDF */}
        {preview && file && (
          <div className="space-y-1.5 text-xs" role="search" aria-label="Search uploaded PDF text">
            <form
              className="flex items-center gap-2"
              onSubmit={event => { event.preventDefault(); void runSearch(); }}
            >
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden="true" />
                <input
                  id="pdf-text-search"
                  type="search"
                  value={query}
                  maxLength={200}
                  placeholder="Search text in this PDF"
                  aria-label="Search text in this PDF"
                  onChange={event => setQuery(event.target.value)}
                  onKeyDown={event => { if (event.key === "Escape" && (query || searchResult)) { event.stopPropagation(); clearSearch(); } }}
                  className="w-full rounded-lg border border-slate-300 bg-white py-1.5 pl-8 pr-8 text-xs text-slate-800 placeholder:text-slate-400 focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-sky-900"
                />
                {(query || searchResult) && (
                  <button
                    type="button"
                    onClick={clearSearch}
                    aria-label="Clear search"
                    title="Clear search"
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <button
                type="submit"
                disabled={searching || query.trim().length < 2}
                className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-sky-200 px-3 py-1.5 font-semibold text-sky-700 hover:bg-sky-50 disabled:opacity-40 dark:border-sky-800 dark:text-sky-300 dark:hover:bg-sky-950/40 cursor-pointer disabled:cursor-not-allowed"
              >
                {searching && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                <span>{searching ? "Searching" : "Search"}</span>
              </button>
            </form>

            {searchError && (
              <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-200">
                {searchError}
              </p>
            )}

            {searchResult && (
              <div aria-live="polite" className="space-y-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-slate-600 dark:text-slate-300">
                    {searchResult.total_matches === 0
                      ? <>No matches for <strong>“{searchResult.query}”</strong> in the PDF text.</>
                      : <><strong>{searchResult.total_matches}</strong> match{searchResult.total_matches === 1 ? "" : "es"} on <strong>{searchResult.pages_matched}</strong> page{searchResult.pages_matched === 1 ? "" : "s"}</>}
                  </p>
                  {searchResult.matches.length > 1 && (
                    <div className="flex items-center gap-1">
                      <button type="button" aria-label="Previous matching page" disabled={activeMatch <= 0}
                        onClick={() => showMatch(activeMatch - 1)}
                        className="rounded-lg border border-slate-200 bg-white p-1 text-slate-600 hover:bg-slate-50 disabled:opacity-30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 cursor-pointer">
                        <ChevronLeft className="h-3.5 w-3.5" />
                      </button>
                      <span className="px-1 font-mono font-bold text-slate-600 dark:text-slate-300">{activeMatch + 1} / {searchResult.matches.length}</span>
                      <button type="button" aria-label="Next matching page" disabled={activeMatch >= searchResult.matches.length - 1}
                        onClick={() => showMatch(activeMatch + 1)}
                        className="rounded-lg border border-slate-200 bg-white p-1 text-slate-600 hover:bg-slate-50 disabled:opacity-30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 cursor-pointer">
                        <ChevronRight className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </div>

                {searchResult.total_matches === 0 && searchResult.pages_with_text < searchResult.pages_searched && (
                  <p className="text-[11px] text-amber-700 dark:text-amber-300">
                    {searchResult.pages_searched - searchResult.pages_with_text} page(s) have no readable text (scanned or image-only), so they cannot be searched.
                  </p>
                )}

                {searchResult.matches.length > 0 && (
                  <ul className="max-h-36 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-700">
                    {searchResult.matches.map((match, index) => (
                      <li key={match.page}>
                        <button
                          type="button"
                          onClick={() => showMatch(index)}
                          aria-current={index === activeMatch ? "true" : undefined}
                          className={`flex w-full items-start gap-2 px-2.5 py-1.5 text-left cursor-pointer ${
                            index === activeMatch ? "bg-sky-50 dark:bg-sky-950/40" : "hover:bg-slate-50 dark:hover:bg-slate-800/60"
                          }`}
                        >
                          <span className="shrink-0 font-mono font-bold text-slate-700 dark:text-slate-200">
                            p. {match.page}
                            {match.count > 1 && <span className="ml-1 font-normal text-slate-400">×{match.count}</span>}
                          </span>
                          <span className="min-w-0 break-words text-slate-600 dark:text-slate-300">
                            {match.before}
                            <mark className="rounded bg-amber-200 px-0.5 text-slate-900 dark:bg-amber-400/80">{match.match}</mark>
                            {match.after}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {searchResult.matches.length > 0 && (
                  <p className="text-[11px] text-slate-500">
                    To highlight the words on the page, click inside the PDF, press <kbd className="rounded border border-slate-300 px-1 font-mono dark:border-slate-600">Ctrl</kbd>+<kbd className="rounded border border-slate-300 px-1 font-mono dark:border-slate-600">F</kbd> and paste (the search text is copied).
                  </p>
                )}
                {searchResult.truncated && (
                  <p className="text-[11px] text-slate-500">Showing the first {searchResult.matches.length} matching pages. Refine the search to narrow it.</p>
                )}
              </div>
            )}
          </div>
        )}

        {preview ? (
          <iframe
            key={`${preview}-${currentPage}`}
            title="Uploaded PDF preview"
            src={`${preview}#page=${currentPage}`}
            className="min-h-[520px] lg:min-h-[620px] flex-1 w-full rounded-xl border border-slate-200 dark:border-slate-700 shadow-2xs bg-white"
          />
        ) : (
          <div className="flex min-h-[300px] flex-1 items-center justify-center rounded-xl border border-dashed border-slate-200 text-xs text-slate-400 dark:border-slate-700">
            No PDF preview available
          </div>
        )}

        <p className="text-[11px] text-slate-500">
          Page numbers follow the uploaded PDF viewer. Use the copied search text to locate wording within a page. Missing source text points to nearby text.
        </p>
      </section>

      {/* Expanded / Fullscreen Modal Overlay */}
      {expanded && preview && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Expanded PDF preview"
          className="fixed inset-0 z-50 flex flex-col bg-slate-950/80 p-3 sm:p-5 backdrop-blur-xs animate-in fade-in duration-150"
        >
          <div className="flex flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900">
            {/* Modal Header */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-3 sm:px-5 sm:py-3.5 dark:border-slate-800">
              <div className="flex items-center gap-3 min-w-0">
                <span className="rounded-lg bg-sky-100 p-1.5 text-sky-700 dark:bg-sky-950 dark:text-sky-300">
                  <Maximize2 className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-bold text-slate-900 dark:text-slate-100">
                    {filename || "PDF Document Preview"}
                  </h3>
                  <p className="text-xs text-slate-500">Full-size PDF inspection view</p>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {/* Previous and Next Change Stepper in Modal */}
                {changedPages.length > 0 && (
                  <div className="flex items-center rounded-xl border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-800 text-xs">
                    <button
                      type="button"
                      disabled={prevChangedPage === null}
                      onClick={() => handleStepChange("prev")}
                      className="rounded-lg px-2 py-1 font-semibold text-slate-600 hover:bg-white disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer flex items-center gap-1"
                    >
                      <ChevronLeft className="h-3.5 w-3.5" />
                      <span>Prev change</span>
                    </button>
                    <span className="text-slate-300 dark:text-slate-600">|</span>
                    <button
                      type="button"
                      disabled={nextChangedPage === null}
                      onClick={() => handleStepChange("next")}
                      className="rounded-lg px-2 py-1 font-semibold text-slate-600 hover:bg-white disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer flex items-center gap-1"
                    >
                      <span>Next change</span>
                      <ChevronRight className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}

                {/* Page Controls in Expanded Modal */}
                <div className="flex items-center rounded-xl border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-800">
                  <button
                    type="button"
                    disabled={currentPage <= 1}
                    onClick={() => handlePageStep(-1)}
                    className="rounded-lg p-1 text-slate-600 hover:bg-white disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <span className="px-3 text-xs font-mono font-bold text-slate-800 dark:text-slate-200">
                    Page {currentPage}{totalPages ? ` of ${totalPages}` : ""}
                  </span>
                  <button
                    type="button"
                    disabled={totalPages ? currentPage >= totalPages : false}
                    onClick={() => handlePageStep(1)}
                    className="rounded-lg p-1 text-slate-600 hover:bg-white disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>

                {currentPage !== issuePage && issuePage > 0 && (
                  <button
                    type="button"
                    onClick={handleReturnToIssuePage}
                    className="inline-flex items-center gap-1 rounded-xl bg-sky-50 px-2.5 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-100 dark:bg-sky-950 dark:text-sky-300 cursor-pointer"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    <span>Jump to issue (p. {issuePage})</span>
                  </button>
                )}

                <a
                  href={`${preview}#page=${currentPage}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Open in new browser tab"
                  className="inline-flex items-center justify-center rounded-xl border border-slate-200 p-2 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800 cursor-pointer"
                >
                  <ExternalLink className="h-4 w-4" />
                </a>

                <button
                  type="button"
                  onClick={() => setExpanded(false)}
                  title="Close expanded view (Esc)"
                  className="inline-flex items-center justify-center rounded-xl bg-slate-100 p-2 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 cursor-pointer"
                >
                  <Minimize2 className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Changed pages strip in modal */}
            {changedPages.length > 0 && (
              <div className="flex items-center gap-1.5 overflow-x-auto px-4 py-2 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
                <span className="shrink-0 font-bold uppercase tracking-wider text-[10px] text-slate-500 flex items-center gap-1">
                  <Sparkles className="h-3 w-3 text-amber-500" />
                  <span>Changed pages:</span>
                </span>
                <div className="flex items-center gap-1">
                  {changedPages.map((p) => {
                    const count = findings?.filter((f) => findingOnPdfPage(f, p)).length || 0;
                    const hasError = findings?.some((f) => findingOnPdfPage(f, p) && f.severity === "error");
                    const isActive = currentPage === p;
                    return (
                      <button
                        key={p}
                        type="button"
                        onClick={() => handleJumpToPage(p)}
                        className={`inline-flex items-center gap-1 rounded-lg px-2 py-0.5 font-mono text-xs font-bold transition-all cursor-pointer ${
                          isActive
                            ? "bg-sky-600 text-white shadow-2xs"
                            : hasError
                            ? "bg-white border border-rose-200 text-rose-700 dark:bg-slate-800 dark:text-rose-300"
                            : "bg-white border border-amber-200 text-amber-700 dark:bg-slate-800 dark:text-amber-300"
                        }`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${isActive ? "bg-white" : hasError ? "bg-rose-500" : "bg-amber-500"}`} />
                        <span>Page {p}</span>
                        <span className="opacity-75">({count})</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Modal Iframe Body */}
            <div className="flex-1 w-full bg-slate-100 dark:bg-slate-950 p-2 sm:p-3">
              <iframe
                key={`modal-${preview}-${currentPage}`}
                title="Expanded uploaded PDF preview"
                src={`${preview}#page=${currentPage}`}
                className="h-full w-full rounded-xl border border-slate-200 dark:border-slate-800 shadow-inner bg-white"
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
