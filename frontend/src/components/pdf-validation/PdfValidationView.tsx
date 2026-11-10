"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Download,
  ExternalLink,
  FileCheck,
  Loader2,
  Upload,
  FileText,
  Globe,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Clock,
  ShieldCheck,
  Layers,
  Check,
  X,
  RefreshCw,
  BookOpen,
  FileSearch,
  Info,
  PanelRight,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  Search,
  Sparkles,
  UploadCloud,
  Plus,
  Trash2
} from "lucide-react";
import {
  discoverPdfSource,
  discoverReferenceDocument,
  fetchPdfValidationConfiguration,
  checkPdfScope,
  PdfDiscoveryTrail,
  PdfHistoricalReference,
  PdfReference,
  pdfReferenceKey,
  PdfSourceMode,
  PdfValidationConfiguration,
  PdfValidationOptions,
  PdfValidationResult
} from "@/lib/pdfValidation";
import { PdfDiscoveryPath } from "./PdfDiscoveryTrail";
import { checkPdfFiles, PdfQueueItem, validatePdfQueue } from "@/lib/pdfValidationQueue";
import { logClientEvent } from "@/lib/api";
import { PdfValidationProcessingModal } from "./PdfValidationProcessingModal";
import { PdfValidationPreview } from "./PdfValidationPreview";
import { PdfValidationDownloads } from "./PdfValidationDownloads";
import { PdfValidationDetailsDrawer } from "./PdfValidationDetailsDrawer";
import { PdfSourceCoverage } from "./PdfSourceCoverage";
import { PdfFindingDiffInspector } from "./PdfFindingDiffInspector";
import { findingOnPdfPage, findingPageLabel, findingPdfPages } from "@/lib/pdfFindingLocation";
import { PdfValidationScope } from "./PdfValidationScope";
import { PdfHistoricalSources, PdfValidationHistory } from "./PdfValidationHistory";

const STATUS = {
  match: {
    label: "Match",
    color: "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200",
    badgeBg: "bg-emerald-500"
  },
  mismatch: {
    label: "Mismatch",
    color: "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200",
    badgeBg: "bg-rose-500"
  },
  needs_review: {
    label: "Needs review",
    color: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200",
    badgeBg: "bg-amber-500"
  },
  unable: {
    label: "Unable to validate",
    color: "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200",
    badgeBg: "bg-slate-500"
  }
};

const COMPARISON = {
  exact_file: "Exact file comparison",
  content: "Extracted text comparison",
  not_checked: "Comparison not completed"
};

const PANEL = "rounded-2xl border border-slate-200/80 bg-white/95 p-4 sm:p-5 shadow-soft-card backdrop-blur-xs transition-all dark:border-slate-800 dark:bg-slate-900/95";
const BUTTON = "inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-2xs hover:bg-slate-50 active:scale-[0.99] disabled:opacity-50 transition-all cursor-pointer dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700";

function downloadReport(result: PdfValidationResult) {
  logClientEvent("report_downloaded", { file: result.filename, status: result.status });
  const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${result.filename.replace(/\.pdf$/i, "")}-validation-report.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function PdfValidationView({active = true}: {active?: boolean}) {
  const [files, setFiles] = useState<File[]>([]);
  const [activeFile, setActiveFile] = useState(0);
  const [outcomes, setOutcomes] = useState<PdfQueueItem[]>([]);
  const [showResults, setShowResults] = useState(false);
  const [processingFile, setProcessingFile] = useState(0);
  const [uri, setUri] = useState("");
  const [scope, setScope] = useState<PdfValidationOptions>({ workflow: "current" });
  const [historicalSources, setHistoricalSources] = useState<PdfHistoricalReference[]>([]);
  const [activeVersion, setActiveVersion] = useState(0);
  const [reference, setReference] = useState("");
  const [references, setReferences] = useState<PdfReference[]>([]);
  const [configuration, setConfiguration] = useState<PdfValidationConfiguration | null>(null);
  const [configurationError, setConfigurationError] = useState("");
  const [configurationAttempt, setConfigurationAttempt] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [discoveryMessage, setDiscoveryMessage] = useState("");
  const [discoveryTrail, setDiscoveryTrail] = useState<PdfDiscoveryTrail | null>(null);
  const referenceMode = scope.source_mode === "reference" && scope.workflow !== "date_range";
  const [previewSource, setPreviewSource] = useState<{ file: File; url: string } | null>(null);
  const [selected, setSelected] = useState(0);
  const [issueFilter, setIssueFilter] = useState<"all" | "error" | "warning" | "info">("all");
  const [pageFilter, setPageFilter] = useState<number | "all">("all");
  const [activePreviewPage, setActivePreviewPage] = useState<number>(1);
  const [issueSearch, setIssueSearch] = useState("");
  const [showLimitations, setShowLimitations] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const detailsTrigger = useRef<HTMLButtonElement>(null);
  const [reviewedIssues, setReviewedIssues] = useState<Set<number>>(new Set());
  const [issuesListPage, setIssuesListPage] = useState<number>(1);
  const [pageChipsPage, setPageChipsPage] = useState<number>(1);

  const request = useRef<AbortController | null>(null);
  const activeView = useRef(active);
  activeView.current = active;
  const resultPanel = useRef<HTMLElement | null>(null);
  const container = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const addInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileSelector = useRef<HTMLDivElement | null>(null);
  const file = files[activeFile];
  const preview = previewSource?.file === file ? previewSource?.url || "" : "";
  const outcome = outcomes[activeFile];
  const report = outcome?.result;
  const result = report?.versions?.[activeVersion]?.result ?? report;

  useEffect(() => {
    const controller = new AbortController();
    setConfigurationError("");
    fetchPdfValidationConfiguration(controller.signal)
      .then(setConfiguration)
      .catch((error) => {
        if (!controller.signal.aborted) {
          setConfigurationError(error.message || "Could not load validation limits.");
        }
      });
    return () => {
      controller.abort();
      request.current?.abort();
    };
  }, [configurationAttempt]);

  useEffect(() => {
    if (!file) {
      setPreviewSource(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewSource({ file, url });
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (activeView.current && showResults && !busy) {
      resultPanel.current?.focus({ preventScroll: true });
      fileSelector.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }, [showResults, busy]);

  function resetResult() {
    request.current?.abort();
    setOutcomes([]);
    setShowResults(false);
    setReferences([]);
    setHistoricalSources([]);
    setActiveVersion(0);
    setReference("");
    setSelected(0);
    setIssueFilter("all");
    setPageFilter("all");
    setActivePreviewPage(1);
    setIssueSearch("");
    setShowLimitations(false);
    setShowDetails(false);
    setError("");
    setDiscoveryMessage("");
    setDiscoveryTrail(null);
    setReviewedIssues(new Set());
    setIssuesListPage(1);
    setPageChipsPage(1);
  }

  function handleNewPdfValidation() {
    logClientEvent("new_validation_clicked");
    resetResult();
    container.current?.scrollTo({top: 0});
    request.current = null;
    setFiles([]);
    setActiveFile(0);
    setProcessingFile(0);
    setUri("");
    setScope({ workflow: "current" });
    setBusy(false);
    setDiscovering(false);
    setPreviewSource(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    if (addInputRef.current) {
      addInputRef.current.value = "";
    }
  }

  function cancelRequest() {
    logClientEvent("cancel_clicked", { discovering, files: files.length });
    request.current?.abort();
    request.current = null;
    setBusy(false);
    setDiscovering(false);
    setOutcomes((items) => items.map((item) =>
      item.state === "pending" || item.state === "processing" ? { state: "cancelled" } : item));
    setShowResults(outcomes.some((item) => item.result || item.state === "error"));
    setActiveFile(0);
  }

  function validUri() {
    try {
      const parsed = new URL(uri.trim());
      if (["https:", "http:"].includes(parsed.protocol) && !parsed.username && !parsed.password) return true;
      throw new Error();
    } catch {
      setError("Enter a valid HTTP or HTTPS document URL.");
      return false;
    }
  }

  async function findPdfs() {
    if (busy || !validUri()) return;
    try { checkPdfScope(scope); } catch (error) {
      setError(error instanceof Error ? error.message : "Choose valid comparison dates.");
      return;
    }
    if (referenceMode && !files.length) {
      setError("Choose the PDF first. A Reference URL is searched for the uploaded document.");
      return;
    }
    logClientEvent("find_documents_clicked", { workflow: scope.workflow ?? "current", source_mode: scope.source_mode ?? "content" });
    const controller = new AbortController();
    request.current?.abort();
    request.current = controller;
    setBusy(true);
    setDiscovering(true);
    setError("");
    setOutcomes([]);
    setShowResults(false);
    setDiscoveryMessage("");
    setDiscoveryTrail(null);
    setReferences([]);
    setHistoricalSources([]);
    setReference("");
    try {
      if (referenceMode) {
        const found = await discoverReferenceDocument(files[0], uri, controller.signal);
        if (!controller.signal.aborted) {
          setDiscoveryTrail(found.discovery ?? null);
          setDiscoveryMessage(found.summary);
          logClientEvent("reference_discovery_finished", { status: found.discovery?.status ?? found.source_type,
            found: found.references[0]?.url ?? "", file: files[0].name });
        }
        return;
      }
      const response = await discoverPdfSource(uri, controller.signal, scope);
      if (!controller.signal.aborted) {
        setReferences(response.references);
        setHistoricalSources(response.versions ?? []);
        setReference(response.references.length === 1 && response.references[0].available ? pdfReferenceKey(response.references[0]) : "");
        setDiscoveryMessage(response.summary);
      }
    } catch (error) {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Could not find PDFs. Try again.");
    } finally {
      if (request.current === controller) {
        request.current = null;
        setBusy(false);
        setDiscovering(false);
      }
    }
  }

  function selectFiles(next: File[]) {
    setOutcomes([]);
    setShowResults(false);
    setActiveFile(0);
    setSelected(0);
    setError("");
    setFiles([]);
    if (!next.length || !configuration) {
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    try {
      checkPdfFiles(next, configuration);
      setFiles(next);
      logClientEvent("files_selected", { count: next.length, names: next.map(item => item.name).join(", ") });
    } catch (error) {
      if (fileInputRef.current) fileInputRef.current.value = "";
      setError(error instanceof Error ? error.message : "Choose valid PDF files.");
      logClientEvent("files_rejected", { count: next.length, reason: error instanceof Error ? error.message : "invalid files" }, "warning");
    }
  }

  function appendFiles(next: File[]) {
    if (!configuration) return;
    const combined = [...files, ...next];
    try {
      checkPdfFiles(combined, configuration);
      setFiles(combined);
      setError("");
      logClientEvent("files_added", { added: next.length, total: combined.length });
    } catch (error) {
      setError(error instanceof Error ? error.message : "Choose valid PDF files.");
      logClientEvent("files_rejected", { count: next.length, reason: error instanceof Error ? error.message : "invalid files" }, "warning");
    }
  }

  function removeFile(indexToRemove: number) {
    const remaining = files.filter((_, idx) => idx !== indexToRemove);
    logClientEvent("file_removed", { file: files[indexToRemove]?.name ?? "", remaining: remaining.length });
    selectFiles(remaining);
  }

  function handleDragOver(event: React.DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    if (!busy && !isDragging) setIsDragging(true);
  }

  function handleDragLeave(event: React.DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);
  }

  function handleDrop(event: React.DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);
    if (busy || !configuration) return;
    const dropped = Array.from(event.dataTransfer.files || []);
    if (!dropped.length) return;
    if (files.length > 0) {
      appendFiles(dropped);
    } else {
      selectFiles(dropped);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!files.length || !configuration || busy || !validUri()) return;
    try { checkPdfScope(scope); } catch (error) {
      setError(error instanceof Error ? error.message : "Choose valid comparison dates.");
      return;
    }
    logClientEvent("validate_clicked", { files: files.length, workflow: scope.workflow ?? "current",
      source_mode: referenceMode ? "reference" : "content", url: uri.trim() });
    const controller = new AbortController();
    request.current?.abort();
    request.current = controller;
    setBusy(true);
    setDiscovering(false);
    setDiscoveryMessage("");
    setError("");
    setSelected(0);
    setActiveFile(0);
    setActiveVersion(0);
    setShowResults(false);
    setOutcomes(files.map(() => ({ state: "pending" })));
    setProcessingFile(0);
    let hasResult = false;
    try {
      const selectedReference = references.find(item => pdfReferenceKey(item) === reference);
      const selectedUrl = selectedReference?.url ?? reference;
      const validationScope: PdfValidationOptions = referenceMode ? {...scope, source_mode: "reference", archive_member: undefined}
        : {...scope, source_mode: "content", ...(selectedReference?.archive_member ? {archive_member: selectedReference.archive_member} : {})};
      const reason = await validatePdfQueue(files, uri, scope.workflow === "date_range" || referenceMode ? undefined : selectedUrl || undefined,
        configuration, controller.signal, (index, item) => {
        if (controller.signal.aborted) return;
        if (item.state === "processing") setProcessingFile(index);
        setOutcomes((items) => items.map((previous, position) => position === index ? item : previous));
        if (item.result) {
          hasResult = true;
          setReferences(item.result.references);
          const nextReferences = item.result.references;
          setReference(previous => nextReferences.some(ref => pdfReferenceKey(ref) === previous) ? previous
            : nextReferences.length === 1 && nextReferences[0].available ? pdfReferenceKey(nextReferences[0]) : "");
        }
        if (item.error && files.length === 1) setError(item.error);
        if (item.error) logClientEvent("file_failed", { file: files[index]?.name ?? "", reason: item.error }, "warning");
      }, validationScope);
      logClientEvent("queue_finished", { files: files.length, reason: reason ?? "completed", cancelled: controller.signal.aborted });
      if (!controller.signal.aborted) {
        setShowResults(hasResult || files.length > 1);
        if (reason === "reference_required") setError("Choose the intended reference document before processing the remaining files.");
        if (reason === "stopped" && files.length > 1) setError("Processing stopped. Return to the inputs to retry the queue.");
        if (reason === "source_unavailable" && files.length > 1) setError("The website could not be accessed. The remaining files were not processed.");
        if (reason === "history_unavailable" && files.length > 1) setError("No historical versions were available for this range. The remaining files were not processed.");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(error instanceof Error ? error.message : "Validation failed. Try again.");
      }
    } finally {
      if (request.current === controller) {
        setBusy(false);
        request.current = null;
      }
    }
  }

  const allFindings = useMemo(() => result?.findings || [], [result?.findings]);
  const errorCount = allFindings.filter((f) => f.severity === "error").length;
  const warningCount = allFindings.filter((f) => f.severity === "warning").length;
  const infoCount = allFindings.filter((f) => f.severity === "info").length;

  const changedPages = React.useMemo(() => {
    const set = new Set<number>();
    for (const item of allFindings) {
      findingPdfPages(item, result?.pdf_pages ?? 2000).forEach(page => set.add(page));
    }
    return Array.from(set).sort((a, b) => a - b);
  }, [allFindings, result?.pdf_pages]);

  const filteredFindings = allFindings.filter((item) => {
    if (issueFilter !== "all" && item.severity !== issueFilter) return false;
    if (pageFilter !== "all" && !findingOnPdfPage(item, pageFilter)) return false;
    if (!issueSearch.trim()) return true;
    const q = issueSearch.toLowerCase();
    return (
      item.message.toLowerCase().includes(q) ||
      (item.source_heading && item.source_heading.toLowerCase().includes(q)) ||
      (item.pdf_page && String(item.pdf_page).includes(q)) ||
      (item.expected && item.expected.toLowerCase().includes(q)) ||
      (item.actual && item.actual.toLowerCase().includes(q))
    );
  });

  const ISSUES_PER_PAGE = 10;
  const totalIssuePages = Math.max(1, Math.ceil(filteredFindings.length / ISSUES_PER_PAGE));
  const safeIssuePage = Math.min(Math.max(1, issuesListPage), totalIssuePages);
  const paginatedFindings = filteredFindings.slice(
    (safeIssuePage - 1) * ISSUES_PER_PAGE,
    safeIssuePage * ISSUES_PER_PAGE
  );

  const CHIPS_PER_PAGE = 10;
  const totalChipsPages = Math.max(1, Math.ceil(changedPages.length / CHIPS_PER_PAGE));
  const safeChipsPage = Math.min(Math.max(1, pageChipsPage), totalChipsPages);
  const visibleChangedPages = changedPages.slice(
    (safeChipsPage - 1) * CHIPS_PER_PAGE,
    safeChipsPage * CHIPS_PER_PAGE
  );

  // Compute pages where all issues have been marked as reviewed.
  const reviewedPages = useMemo(() => {
    const pages = new Set<number>();
    for (const pageNum of changedPages) {
      const pageIssues = allFindings
        .map((f, idx) => ({ finding: f, idx }))
        .filter(({ finding }) => findingOnPdfPage(finding, pageNum));
      if (pageIssues.length > 0 && pageIssues.every(({ idx }) => reviewedIssues.has(idx))) {
        pages.add(pageNum);
      }
    }
    return pages;
  }, [changedPages, allFindings, reviewedIssues]);

  function toggleIssueReviewed(originalIndex: number) {
    setReviewedIssues((prev) => {
      const next = new Set(prev);
      if (next.has(originalIndex)) {
        next.delete(originalIndex);
      } else {
        next.add(originalIndex);
      }
      return next;
    });
  }

  function togglePageReviewed(pageNum: number) {
    const pageIssueIndices = allFindings
      .map((f, idx) => ({ finding: f, idx }))
      .filter(({ finding }) => findingOnPdfPage(finding, pageNum))
      .map(({ idx }) => idx);

    setReviewedIssues((prev) => {
      const next = new Set(prev);
      const isFullyReviewed = pageIssueIndices.length > 0 && pageIssueIndices.every((idx) => next.has(idx));
      if (isFullyReviewed) {
        pageIssueIndices.forEach((idx) => next.delete(idx));
      } else {
        pageIssueIndices.forEach((idx) => next.add(idx));
      }
      return next;
    });
  }

  const finding = allFindings[selected];

  // Keep preview page synchronized with selected finding.
  useEffect(() => {
    if (finding?.pdf_page) {
      setActivePreviewPage(current => findingOnPdfPage(finding, current) ? current : finding.pdf_page!);
    }
  }, [finding]);

  const previewPage = activePreviewPage || finding?.pdf_page || 1;
  const currentFilteredIndex = finding ? filteredFindings.indexOf(finding) : -1;

  function handleStepIssue(delta: number) {
    if (filteredFindings.length === 0) return;
    const baseIndex = currentFilteredIndex === -1 ? 0 : currentFilteredIndex;
    const nextFiltered = Math.min(Math.max(0, baseIndex + delta), filteredFindings.length - 1);
    const targetFinding = filteredFindings[nextFiltered];
    const targetIndex = allFindings.indexOf(targetFinding);
    if (targetIndex !== -1) {
      setSelected(targetIndex);
      const targetPage = Math.floor(nextFiltered / ISSUES_PER_PAGE) + 1;
      setIssuesListPage(targetPage);
    }
  }

  return (
    <div ref={container} className="w-full h-full min-h-0 overflow-y-auto p-3 pt-14 sm:p-4 sm:pt-14 lg:p-5 lg:pt-4 text-slate-800 dark:text-slate-200 font-sans transition-all duration-300">
      <div className="w-full max-w-none space-y-4 sm:space-y-4.5">
        {/* View 1: Upload Form & Controls View (Shown initially before validation completes) */}
        {!showResults && (
          <div className="mx-auto w-full max-w-2xl">
            {/* Main Validation Input Form: Centered Square Box */}
            <form onSubmit={submit} className="relative rounded-3xl border border-slate-200/90 bg-white/95 p-6 sm:p-7 shadow-xl shadow-slate-200/50 backdrop-blur-sm transition-all dark:border-slate-800 dark:bg-slate-900/95 dark:shadow-slate-950/40 space-y-5">
              {/* Box Header: PDF Content URI Validation */}
              <div className="border-b border-slate-100 dark:border-slate-800 pb-4 space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-600 via-indigo-600 to-purple-600 text-white flex items-center justify-center shadow-md shadow-sky-500/20 shrink-0">
                      <FileCheck className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h1 className="text-base sm:text-lg font-black tracking-tight text-slate-900 dark:text-slate-100">
                          PDF Content URI Validation
                        </h1>
                        <span className="text-[10px] font-extrabold uppercase px-2 py-0.5 rounded-full bg-sky-100 dark:bg-sky-950/80 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800 font-mono">
                          Pre-Production QC
                        </span>
                        <span className="text-[10px] font-extrabold uppercase px-2 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-950/80 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800 font-mono">
                          Authenticity
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 dark:text-slate-400 font-medium truncate">
                        Check up to {configuration?.max_files ?? 10} PDFs against one website document URL.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Feature Highlights Badges */}
                <div className="flex items-center gap-2 flex-wrap text-[11px] font-semibold text-slate-600 dark:text-slate-300">

                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-lg bg-slate-50 dark:bg-slate-800/80 border border-slate-200/80 dark:border-slate-700/80 shadow-2xs">
                    <FileText className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-400" />
                    <span>Text Diffing</span>
                  </span>
                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-lg bg-slate-50 dark:bg-slate-800/80 border border-slate-200/80 dark:border-slate-700/80 shadow-2xs">
                    <Layers className="h-3.5 w-3.5 text-purple-600 dark:text-purple-400" />
                    <span>Page Locator</span>
                  </span>
                </div>
              </div>

              <PdfValidationScope value={scope} disabled={busy} maxVersions={configuration?.max_versions ?? 10}
                onChange={value => { resetResult(); setScope(value); }} />

              {/* PDF File Upload Input (Center Dropzone for Multiple PDFs) */}
              <div className="flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <label htmlFor="validation-pdf" className="block text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
                    PDF files
                  </label>
                  <span className="text-[11px] font-semibold text-sky-600 dark:text-sky-400 bg-sky-50 dark:bg-sky-950/60 px-2 py-0.5 rounded-md border border-sky-100 dark:border-sky-900/40">
                    Multi-file upload (1–{configuration?.max_files ?? 10})
                  </span>
                </div>

                <div
                  onDragOver={handleDragOver}
                  onDragEnter={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  className={`relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed transition-all ${
                    isDragging
                      ? "border-sky-500 bg-sky-50/90 dark:border-sky-400 dark:bg-sky-950/50 ring-4 ring-sky-500/15 scale-[1.01]"
                      : files.length
                      ? "border-sky-300/80 bg-sky-50/30 dark:border-sky-800/80 dark:bg-sky-950/20 p-4 sm:p-5"
                      : "border-slate-300 hover:border-sky-400 bg-slate-50/70 hover:bg-sky-50/30 dark:border-slate-700 dark:bg-slate-800/40 dark:hover:bg-slate-800/70 p-6 sm:p-8 cursor-pointer"
                  }`}
                  onClick={() => {
                    if (!files.length && !busy && configuration) {
                      fileInputRef.current?.click();
                    }
                  }}
                >
                  <input
                    id="validation-pdf"
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,application/pdf"
                    disabled={busy || !configuration}
                    onChange={(event) => selectFiles(Array.from(event.target.files || []))}
                    className="sr-only"
                  />
                  <input
                    ref={addInputRef}
                    type="file"
                    multiple
                    accept=".pdf,application/pdf"
                    disabled={busy || !configuration}
                    onChange={(event) => {
                      appendFiles(Array.from(event.target.files || []));
                      event.target.value = "";
                    }}
                    className="sr-only"
                  />

                  {!files.length ? (
                    <div className="flex flex-col items-center text-center select-none pointer-events-none">
                      <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-tr from-sky-500 to-indigo-600 text-white shadow-md shadow-sky-500/25 group-hover:scale-105 transition-transform">
                        <UploadCloud className="h-7 w-7" />
                      </div>
                      <p className="text-sm sm:text-base font-bold text-slate-900 dark:text-slate-100">
                        Drop your PDF files here, or <span className="text-sky-600 underline dark:text-sky-400">browse</span>
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400 max-w-sm">
                        Select multiple PDF files to validate against one target URL
                      </p>
                      <div className="mt-3 flex items-center justify-center gap-2 text-[11px] text-slate-400 dark:text-slate-500">
                        <span className="rounded-md bg-white dark:bg-slate-800 px-2 py-0.5 font-mono border border-slate-200/60 dark:border-slate-700">.PDF only</span>
                        <span>•</span>
                        <span>Up to {configuration?.max_files ?? 10} files</span>
                        <span>•</span>
                        <span>Max 100 MB</span>
                      </div>
                    </div>
                  ) : (
                    <div className="w-full space-y-3">
                      <div className="flex items-center justify-between border-b border-sky-100 dark:border-sky-900/40 pb-2">
                        <span className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
                          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                          <span>Selected PDFs ({files.length} of {configuration?.max_files ?? 10})</span>
                        </span>
                        <div className="flex items-center gap-2">
                          {files.length < (configuration?.max_files ?? 10) && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                addInputRef.current?.click();
                              }}
                              disabled={busy}
                              className="inline-flex items-center gap-1 rounded-lg bg-sky-100 hover:bg-sky-200 text-sky-700 dark:bg-sky-950 dark:hover:bg-sky-900 dark:text-sky-300 px-2.5 py-1 text-xs font-semibold transition-colors cursor-pointer"
                            >
                              <Plus className="h-3 w-3" />
                              <span>Add more</span>
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              selectFiles([]);
                            }}
                            disabled={busy}
                            className="inline-flex items-center gap-1 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30 px-2 py-1 text-xs font-medium transition-colors cursor-pointer"
                            title="Clear all selected files"
                          >
                            <Trash2 className="h-3 w-3" />
                            <span>Clear all</span>
                          </button>
                        </div>
                      </div>

                      <ol
                        aria-label="Selected PDF files"
                        className="max-h-52 w-full space-y-1.5 overflow-y-auto pr-1 text-left"
                      >
                        {files.map((item, index) => (
                          <li
                            key={`${item.name}-${index}`}
                            className="flex items-center justify-between gap-2.5 rounded-xl border border-slate-200/80 bg-white/90 dark:border-slate-800 dark:bg-slate-900/90 px-3 py-2 text-xs shadow-2xs hover:border-sky-300 dark:hover:border-sky-800 transition-colors"
                          >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-sky-100 text-[10px] font-bold font-mono text-sky-700 dark:bg-sky-950 dark:text-sky-300">
                                {index + 1}
                              </span>
                              <FileText className="h-4 w-4 shrink-0 text-sky-600 dark:text-sky-400" />
                              <span className="min-w-0 truncate font-semibold text-slate-800 dark:text-slate-200" title={item.name}>
                                {item.name}
                              </span>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <span className="rounded-md bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 text-[11px] font-mono text-slate-500 dark:text-slate-400">
                                {(item.size / 1024 / 1024).toFixed(2)} MB
                              </span>
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  removeFile(index);
                                }}
                                disabled={busy}
                                className="p-1 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors cursor-pointer"
                                title="Remove file"
                              >
                                <X className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}
                </div>

                <p className="mt-1.5 text-xs text-slate-500">
                  Choose 1 to {configuration?.max_files ?? 10} files. {files.length > 0 ? `${files.length} selected; processed in the order shown.` : "Each file uses the same website URL."}
                </p>
              </div>

              {/* Website URL Field: a direct Content URI, or a Reference URL to search from (single URL for all PDFs) */}
              <div className="flex flex-col">
                <div role="radiogroup" aria-label="Type of website URL" className="mb-2.5 grid grid-cols-2 gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-800/60">
                  {([["content", "Content URI", "The document itself"], ["reference", "Reference URL", "A website page to search from"]] as [PdfSourceMode, string, string][]).map(([mode, title, hint]) => {
                    const chosen = (referenceMode ? "reference" : "content") === mode;
                    const blocked = mode === "reference" && scope.workflow === "date_range";
                    return (
                      <button key={mode} type="button" role="radio" aria-checked={chosen} disabled={busy || blocked}
                        title={blocked ? "Historical date ranges need a Content URI." : undefined}
                        onClick={() => {
                          if (chosen) return;
                          resetResult();
                          setScope(value => ({ ...value, source_mode: mode }));
                          logClientEvent("source_mode_changed", { source_mode: mode });
                        }}
                        className={`rounded-lg px-3 py-1.5 text-left transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 ${
                          chosen ? "bg-white shadow-2xs ring-1 ring-sky-300 dark:bg-slate-900 dark:ring-sky-700" : "hover:bg-white/70 dark:hover:bg-slate-900/50"}`}>
                        <span className={`block text-xs font-bold ${chosen ? "text-sky-700 dark:text-sky-300" : "text-slate-700 dark:text-slate-300"}`}>{title}</span>
                        <span className="block text-[11px] text-slate-500 dark:text-slate-400">{hint}</span>
                      </button>
                    );
                  })}
                </div>
                <div className="flex items-center justify-between mb-1.5">
                  <label htmlFor="validation-uri" className="block text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
                    {referenceMode ? "Reference URL (website starting page)" : "Website document URL (Content URI)"}
                  </label>
                  <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
                    One URL for all PDFs
                  </span>
                </div>
                <div className="relative">
                  <Globe className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
                  <input
                    id="validation-uri"
                    type="url"
                    required
                    maxLength={2048}
                    value={uri}
                    disabled={busy}
                    placeholder="https://publisher.example/document"
                    onChange={(event) => {
                      resetResult();
                      setUri(event.target.value);
                    }}
                    className="w-full rounded-xl border border-slate-200 bg-transparent pl-9 pr-8 py-2.5 text-xs sm:text-sm text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500/20 dark:border-slate-700 font-mono transition-all"
                  />
                  {uri && !busy && (
                    <button
                      type="button"
                      onClick={() => {
                        resetResult();
                        setUri("");
                      }}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-full cursor-pointer"
                      title="Clear URL"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {referenceMode
                      ? "Enter a landing page such as a list of titles. Each PDF is located inside the website before it is compared."
                      : "Enter a PDF, ZIP, or website URL to find the published document."}
                  </p>
                  <button type="button" onClick={findPdfs} disabled={!uri.trim() || !configuration || busy || (referenceMode && !files.length)}
                    title={referenceMode && !files.length ? "Choose a PDF first; it is what the website is searched for." : undefined} className={BUTTON}>
                    <FileSearch className="h-3.5 w-3.5" />
                    <span>{scope.workflow === "date_range" ? "Find versions" : referenceMode ? "Find this PDF on the website" : "Find documents"}</span>
                  </button>
                </div>
              </div>

              {discoveryMessage && (
                <p role="status" className="rounded-xl border border-sky-100 bg-sky-50 p-2.5 text-xs text-sky-800 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
                  {discoveryMessage}
                </p>
              )}

              {referenceMode && discoveryTrail && <PdfDiscoveryPath trail={discoveryTrail} />}

              {historicalSources.length > 0 && <PdfHistoricalSources versions={historicalSources} />}

              {/* References Dropdown */}
              {scope.workflow !== "date_range" && !referenceMode && references.length > 0 && (
                <div className="rounded-xl border border-sky-100 bg-sky-50/50 p-3 dark:border-slate-800 dark:bg-slate-950/40 space-y-1.5">
                  <label htmlFor="validation-reference" className="block text-xs font-bold uppercase tracking-wider text-sky-950 dark:text-sky-200 flex items-center gap-1.5">
                    <BookOpen className="h-3.5 w-3.5" />
                    <span>Reference document on this website</span>
                  </label>
                  <select
                    id="validation-reference"
                    value={reference}
                    disabled={busy}
                    onChange={(event) => {
                      setReference(event.target.value);
                      setOutcomes([]);
                    }}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs sm:text-sm font-medium text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500/20"
                  >
                    <option value="">Select the intended document</option>
                    {references.map((item) => (
                      <option key={pdfReferenceKey(item)} value={pdfReferenceKey(item)} disabled={!item.available}>
                        {item.label} — {item.url}
                        {!item.available ? " (source host unavailable)" : ""}
                      </option>
                    ))}
                  </select>
                  {references.some((item) => !item.available) && (
                    <p className="mt-1 text-xs text-amber-700 dark:text-amber-300 font-medium">
                      For a PDF on another host, enter its direct URL above or ask an administrator to configure approved source hosts.
                    </p>
                  )}
                </div>
              )}

              {/* Configuration Error Alert */}
              {configurationError && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50/80 p-3 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-200">
                  <p role="alert" className="text-xs sm:text-sm font-medium flex items-center gap-1.5">
                    <AlertTriangle className="h-4 w-4 shrink-0 text-rose-600" />
                    <span>{configurationError}</span>
                  </p>
                  <button
                    type="button"
                    onClick={() => setConfigurationAttempt((value) => value + 1)}
                    className={BUTTON}
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    <span>Retry loading limits</span>
                  </button>
                </div>
              )}

              {/* Input Validation Error Alert */}
              {error && (
                <p
                  role="alert"
                  className="flex items-center gap-2 rounded-xl bg-rose-50 px-3.5 py-2 text-xs sm:text-sm font-medium text-rose-700 border border-rose-200 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300"
                >
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </p>
              )}

              {/* Action Buttons & Limits Text */}
              <div className="space-y-3 pt-2 border-t border-slate-100 dark:border-slate-800">
                <button
                  type="submit"
                  disabled={!files.length || !uri.trim() || !configuration || busy
                    || (scope.workflow !== "date_range" && !referenceMode && references.length > 1 && !reference)
                    || (scope.workflow === "date_range" && (!scope.date_start || !scope.date_end))}
                  className="w-full inline-flex items-center justify-center gap-2.5 rounded-xl bg-gradient-to-r from-sky-600 via-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 py-3 px-5 text-sm sm:text-base font-bold text-white shadow-[0_4px_14px_rgba(2,132,199,0.35)] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50 transition-all cursor-pointer"
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                  <span>{busy ? (discovering ? "Finding documents..." : "Validating PDF...") : files.length > 1 ? "Validate PDFs" : "Validate PDF"}</span>
                </button>

                <p className="text-xs text-center text-slate-500 dark:text-slate-400">
                  {configuration
                    ? `Up to ${
                        configuration.max_upload_bytes >= 1024 * 1024
                          ? `${(configuration.max_upload_bytes / 1024 / 1024).toLocaleString()} MB`
                          : `${Math.ceil(configuration.max_upload_bytes / 1024)} KB`
                      }; ${configuration.max_pages.toLocaleString()} pages for text comparison.`
                    : "Loading validation limits..."}
                </p>
              </div>
            </form>
          </div>
        )}

        {/* Validation Progress Modal */}
        {busy && (
          <PdfValidationProcessingModal
            active={active}
            filename={files[processingFile]?.name}
            fileNumber={processingFile + 1}
            fileCount={files.length}
            discovering={discovering}
            onCancel={cancelRequest}
          />
        )}

        {/* View 2: Dedicated Results View (Shown once validation finishes, hides upload form) */}
        {showResults && (
          <>
            {/* Dedicated Results Top Banner with Integrated File Dropdown & Actions */}
            <div
              ref={fileSelector}
              className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border border-slate-200/80 bg-white/95 p-3.5 sm:p-4 shadow-xs transition-all dark:border-slate-800 dark:bg-slate-900/95"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-600 via-indigo-600 to-purple-600 text-white flex items-center justify-center shadow-md shadow-sky-500/20 shrink-0">
                  <FileCheck className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h1 className="text-lg sm:text-xl font-black tracking-tight text-slate-900 dark:text-slate-100">
                      PDF Validation Results
                    </h1>
                    {report && (
                      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-bold ${STATUS[report.status].color}`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${STATUS[report.status].badgeBg}`} />
                        <span>{STATUS[report.status].label}</span>
                      </span>
                    )}
                  </div>

                  {/* Small dropdown for PDF file selection moved directly into results box */}
                  <div className="mt-1 flex items-center gap-2 flex-wrap">
                    {files.length > 1 ? (
                      <div className="flex items-center gap-1.5">
                        <label htmlFor="validation-active-pdf" className="text-[11px] font-bold uppercase text-slate-500 tracking-wider">
                          PDF file:
                        </label>
                        <select
                          id="validation-active-pdf"
                          value={activeFile}
                          onChange={(event) => {
                            setActiveFile(Number(event.target.value));
                            setActiveVersion(0);
                            setSelected(0);
                          }}
                          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-800 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 max-w-[280px] sm:max-w-[340px] truncate shadow-2xs focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
                        >
                          {files.map((item, index) => {
                            const entry = outcomes[index];
                            const label = entry?.result
                              ? STATUS[entry.result.status].label
                              : entry?.state === "error"
                              ? "Failed"
                              : entry?.state === "cancelled"
                              ? "Cancelled"
                              : "Not processed";
                            return (
                              <option key={index} value={index}>
                                {index + 1}. {item.name} ({label})
                              </option>
                            );
                          })}
                        </select>
                        <span className="text-[11px] text-slate-500 font-mono">
                          ({activeFile + 1} of {files.length})
                        </span>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500 dark:text-slate-400 font-medium truncate max-w-xl">
                        {file?.name || result?.filename}
                      </p>
                    )}
                  </div>
                </div>
              </div>

              {/* Top Action Buttons (Single instance, no duplication) */}
              <div className="flex items-center gap-2 flex-wrap shrink-0">
                {result && (
                  <button
                    ref={detailsTrigger}
                    type="button"
                    onClick={() => { logClientEvent("details_opened", { file: result.filename }); setShowDetails(true); }}
                    aria-haspopup="dialog"
                    aria-expanded={showDetails}
                    className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 shadow-2xs transition-all hover:bg-slate-50 cursor-pointer dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                  >
                    <PanelRight className="h-3.5 w-3.5 text-sky-600 dark:text-sky-400" />
                    <span>Details</span>
                  </button>
                )}

                {/* Scope Limitations Button */}
                {result && result.limitations && result.limitations.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setShowLimitations((prev) => !prev)}
                    className={`inline-flex items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-bold shadow-2xs transition-all cursor-pointer ${
                      showLimitations
                        ? "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-700 dark:bg-amber-950/60 dark:text-amber-200"
                        : "border-slate-200 bg-white hover:bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-slate-200"
                    }`}
                    aria-expanded={showLimitations}
                  >
                    <Info className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />
                    <span>Scope Limitations</span>
                    <span className="rounded-full bg-amber-100 dark:bg-amber-900/60 px-1.5 py-0.2 text-[10px] font-mono font-bold text-amber-700 dark:text-amber-300">
                      {result.limitations.length}
                    </span>
                  </button>
                )}

                {result && <PdfValidationDownloads key={`${result.upload_sha256}-${result.source_sha256}-${result.source_url}`} result={result} file={file} />}

                <button
                  type="button"
                  onClick={handleNewPdfValidation}
                  className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-sky-200 bg-sky-50/80 hover:bg-sky-100 text-sky-700 dark:border-sky-800 dark:bg-sky-950/60 dark:hover:bg-sky-900/60 dark:text-sky-300 px-3.5 py-2 text-xs font-bold shadow-2xs hover:shadow-xs active:scale-[0.98] transition-all cursor-pointer"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  <span>New PDF Validation</span>
                </button>

                {result && (
                  <button
                    type="button"
                    onClick={() => downloadReport(report ?? result)}
                    className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-sky-600 hover:bg-sky-700 active:bg-sky-800 text-white px-3.5 py-2 text-xs font-bold shadow-soft-sky active:scale-[0.98] transition-all cursor-pointer dark:bg-sky-600 dark:hover:bg-sky-500"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>Download report</span>
                  </button>
                )}
              </div>
            </div>

            {report?.workflow === "date_range" && <PdfValidationHistory report={report} selected={activeVersion}
              onSelect={index => { setActiveVersion(index); setSelected(0); setIssueFilter("all"); setIssueSearch(""); }} />}

            {/* Toggleable Scope Limitations Panel */}
            {showLimitations && result && result.limitations && result.limitations.length > 0 && (
              <div className="rounded-2xl border border-amber-200/90 bg-amber-50/80 p-3 sm:p-4 text-xs dark:border-amber-900/60 dark:bg-amber-950/30 animate-in fade-in duration-150 shadow-2xs">
                <div className="flex items-center justify-between mb-1.5">
                  <p className="text-xs font-bold uppercase tracking-wider text-amber-900 dark:text-amber-200 flex items-center gap-1.5">
                    <Info className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                    <span>Scope Limitations</span>
                  </p>
                  <button
                    type="button"
                    onClick={() => setShowLimitations(false)}
                    className="p-1 text-amber-700 hover:text-amber-900 dark:text-amber-400 rounded-lg cursor-pointer"
                    aria-label="Close scope limitations"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <ul className="list-disc space-y-1 pl-5 text-slate-700 dark:text-slate-300">
                  {result.limitations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}

            {error && <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">{error}</p>}

            {!result && (
              <>
                <section ref={resultPanel} tabIndex={-1} aria-label="Validation result" className={`${PANEL} space-y-2 focus:outline-none`}>
                  <h2 className="text-lg font-bold">{file?.name}</h2>
                  <p role={outcome?.error ? "alert" : "status"}>{outcome?.error || (outcome?.state === "cancelled"
                    ? "Validation was cancelled for this file. Return to the inputs to validate it."
                    : "This file has not been processed. Return to the inputs to validate it.")}</p>
                </section>
                <PdfValidationPreview active={active} preview={preview} page={1} filename={file?.name} file={file} className={PANEL} />
              </>
            )}

            {result && (
              <>
                {/* Verdict and Overview Summary Panel */}
                <section
                  ref={resultPanel}
                  tabIndex={-1}
                  aria-label="Validation result"
                  className={`${PANEL} space-y-4 animate-in fade-in duration-200 focus:outline-none`}
                >
                  {/* Verdict Header (Without duplicate buttons) */}
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 pb-3 border-b border-slate-100 dark:border-slate-800">
                    <div className="space-y-1.5 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-0.5 text-xs font-bold shadow-2xs ${STATUS[result.status].color}`}>
                          <span className={`h-2 w-2 rounded-full ${STATUS[result.status].badgeBg}`} />
                          <span>{STATUS[result.status].label}</span>
                        </span>
                        <span className="text-[10px] font-mono font-bold text-slate-400 uppercase tracking-wider">
                          Verdict
                        </span>
                      </div>
                      <p className="text-xs sm:text-sm font-semibold text-slate-900 dark:text-slate-100 leading-snug">
                        {result.summary}
                      </p>
                    </div>
                  </div>

              {(result.document_identity === "mismatch" || result.document_identity === "needs_review") && (
                <div role="alert" className="space-y-1 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                  <p className="font-bold">{result.document_identity === "mismatch" ? "PDF and URL refer to different documents" : "Check document identity"}</p>
                  <p>{result.identity_summary}</p>
                  {result.document_identity === "needs_review" && <dl className="grid gap-1 pt-1 text-xs sm:grid-cols-2">
                    <div><dt className="font-semibold">Detected upload title</dt><dd>{result.identity_pdf_title || "No reliable visible title found"}</dd></div>
                    <div><dt className="font-semibold">Detected source title</dt><dd>{result.identity_source_title || "No reliable visible title found"}</dd></div>
                  </dl>}
                  {result.document_identity === "mismatch" && <p>Upload the correct PDF or enter its document URL, then validate again.</p>}
                </div>
              )}

              {result.source_access_issue && <div role="alert" className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                <p className="font-bold">{result.source_access_issue === "captcha" ? "Website requires CAPTCHA or browser verification"
                  : result.source_access_issue === "rate_limited" ? "Website is limiting requests"
                  : result.source_access_issue === "access_denied" ? "Website denied access" : "Website unavailable"}</p>
                <p>The source could not be checked. Open the website to review it manually, or use an accessible direct PDF URL.</p>
                <a href={result.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-semibold underline">
                  Open website <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>}

              {/* Key Metrics Grid */}
              <dl className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
                <div className="rounded-xl border border-slate-100 bg-slate-50/70 p-2.5 dark:border-slate-800 dark:bg-slate-800/40">
                  <dt className="text-xs text-slate-500 flex items-center gap-1">
                    <Layers className="h-3 w-3 text-sky-600 dark:text-sky-400" />
                    <span>Comparison</span>
                  </dt>
                  <dd className="mt-0.5 font-medium text-xs sm:text-sm truncate text-slate-800 dark:text-slate-200">
                    {COMPARISON[result.comparison]}
                  </dd>
                </div>

                <div className="rounded-xl border border-slate-100 bg-slate-50/70 p-2.5 dark:border-slate-800 dark:bg-slate-800/40">
                  <dt className="text-xs text-slate-500 flex items-center gap-1">
                    <FileText className="h-3 w-3 text-indigo-600 dark:text-indigo-400" />
                    <span>PDF pages checked</span>
                  </dt>
                  <dd className="mt-0.5 font-medium text-xs sm:text-sm font-mono text-slate-800 dark:text-slate-200">
                    {result.checked_pdf_pages.toLocaleString()} / {result.pdf_pages?.toLocaleString() ?? "Unknown"}
                  </dd>
                </div>

                <div className="rounded-xl border border-slate-100 bg-slate-50/70 p-2.5 dark:border-slate-800 dark:bg-slate-800/40">
                  <dt className="text-xs text-slate-500 flex items-center gap-1">
                    <Sparkles className="h-3 w-3 text-amber-500" />
                    <span>Pages to review</span>
                  </dt>
                  <dd className="mt-0.5 font-medium text-xs sm:text-sm font-mono text-slate-800 dark:text-slate-200">
                    {changedPages.length} {changedPages.length === 1 ? "page" : "pages"} ({allFindings.length} issue{allFindings.length === 1 ? "" : "s"})
                  </dd>
                </div>

                <div className="rounded-xl border border-slate-100 bg-slate-50/70 p-2.5 dark:border-slate-800 dark:bg-slate-800/40">
                  <dt className="text-xs text-slate-500 flex items-center gap-1">
                    <ShieldCheck className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
                    <span>Coverage</span>
                  </dt>
                  <dd className="mt-0.5 font-medium text-xs sm:text-sm truncate text-slate-800 dark:text-slate-200">
                    {result.coverage_complete ? "Complete for stated scope" : "Incomplete or not checked"}
                  </dd>
                </div>

                <div className="rounded-xl border border-slate-100 bg-slate-50/70 p-2.5 dark:border-slate-800 dark:bg-slate-800/40">
                  <dt className="text-xs text-slate-500 flex items-center gap-1">
                    <Clock className="h-3 w-3 text-slate-600 dark:text-slate-400" />
                    <span>Checked at</span>
                  </dt>
                  <dd className="mt-0.5 font-medium text-xs sm:text-sm font-mono truncate text-slate-800 dark:text-slate-200">
                    {new Date(result.checked_at).toLocaleString()}
                  </dd>
                </div>
              </dl>

              {result.discovery && <PdfDiscoveryPath trail={result.discovery} compact />}
              <PdfSourceCoverage coverage={result.source_coverage} />
            </section>

            {/* Details drawer: source and jurisdiction, comparison scope and dates */}
            {result && <PdfValidationDetailsDrawer result={result} open={showDetails} onClose={() => { setShowDetails(false); detailsTrigger.current?.focus(); }} />}

            {/* Side-by-side Results Grid (Side by side on lg+, stacked on <lg) */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-4.5 min-w-0 items-stretch">
              {/* Column 1: Issues to Review Panel */}
              <section aria-label="Validation findings" className={`${PANEL} min-w-0 space-y-3.5`}>
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800 pb-2">
                  <div className="flex items-center gap-2">
                    {result.findings.length > 0 ? (
                      <AlertTriangle className="h-4 w-4 text-rose-500" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    )}
                    <h2 className="text-sm sm:text-base font-semibold text-slate-900 dark:text-slate-100">
                      Issues to review ({result.findings.length})
                    </h2>
                  </div>

                  {/* Previous / Next Issue Stepper */}
                  {filteredFindings.length > 0 && (
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        aria-label="Previous issue"
                        disabled={currentFilteredIndex <= 0}
                        onClick={() => handleStepIssue(-1)}
                        className="rounded-lg border border-slate-200 bg-white p-1 text-slate-600 hover:bg-slate-50 disabled:opacity-30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer"
                      >
                        <ChevronLeft className="h-3.5 w-3.5" />
                      </button>
                      <span className="px-1.5 text-xs font-mono font-bold text-slate-600 dark:text-slate-300">
                        {currentFilteredIndex >= 0 ? currentFilteredIndex + 1 : 1} / {filteredFindings.length}
                      </span>
                      <button
                        type="button"
                        aria-label="Next issue"
                        disabled={currentFilteredIndex >= filteredFindings.length - 1}
                        onClick={() => handleStepIssue(1)}
                        className="rounded-lg border border-slate-200 bg-white p-1 text-slate-600 hover:bg-slate-50 disabled:opacity-30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 cursor-pointer"
                      >
                        <ChevronRight className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </div>

                {/* Filter & Search Toolbar (Only rendered when findings exist) */}
                {allFindings.length > 0 && (
                  <div className="space-y-2">
                    <div className="flex flex-col sm:flex-row gap-2">
                      {/* Issue Search Bar */}
                      <div className="relative flex-1 min-w-0">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400 pointer-events-none" />
                        <input
                          type="text"
                          value={issueSearch}
                          placeholder="Search issues, pages, or text..."
                          onChange={(e) => setIssueSearch(e.target.value)}
                          className="w-full rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800/80 pl-8 pr-7 py-1 text-xs text-slate-800 dark:text-slate-200 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500/20"
                        />
                        {issueSearch && (
                          <button
                            type="button"
                            onClick={() => setIssueSearch("")}
                            className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        )}
                      </div>

                      {/* Severity Filter Chips */}
                      <div className="flex items-center gap-1 shrink-0 overflow-x-auto pb-0.5">
                        <button
                          type="button"
                          onClick={() => setIssueFilter("all")}
                          className={`rounded-lg px-2 py-1 text-xs font-semibold transition-all cursor-pointer ${
                            issueFilter === "all"
                              ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900 shadow-2xs"
                              : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
                          }`}
                        >
                          All ({allFindings.length})
                        </button>
                        {errorCount > 0 && (
                          <button
                            type="button"
                            onClick={() => setIssueFilter("error")}
                            className={`rounded-lg px-2 py-1 text-xs font-semibold transition-all cursor-pointer ${
                              issueFilter === "error"
                                ? "bg-rose-600 text-white shadow-2xs"
                                : "border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300"
                            }`}
                          >
                            Errors ({errorCount})
                          </button>
                        )}
                        {warningCount > 0 && (
                          <button
                            type="button"
                            onClick={() => setIssueFilter("warning")}
                            className={`rounded-lg px-2 py-1 text-xs font-semibold transition-all cursor-pointer ${
                              issueFilter === "warning"
                                ? "bg-amber-600 text-white shadow-2xs"
                                : "border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300"
                            }`}
                          >
                            Warnings ({warningCount})
                          </button>
                        )}
                        {infoCount > 0 && (
                          <button
                            type="button"
                            onClick={() => setIssueFilter("info")}
                            className={`rounded-lg px-2 py-1 text-xs font-semibold transition-all cursor-pointer ${
                              issueFilter === "info"
                                ? "bg-sky-600 text-white shadow-2xs"
                                : "border border-sky-200 bg-sky-50 text-sky-700 hover:bg-sky-100 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-300"
                            }`}
                          >
                            Info ({infoCount})
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Changed Pages Quick Filter Chips with Checkboxes & Pagination */}
                    {changedPages.length > 0 && (
                      <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 text-[11px] pt-0.5">
                        <span className="font-bold uppercase text-[10px] text-slate-500 tracking-wider shrink-0 flex items-center gap-1">
                          <FileText className="h-3 w-3 text-sky-600 dark:text-sky-400" />
                          <span>Page:</span>
                        </span>
                        <button
                          type="button"
                          onClick={() => {
                            setPageFilter("all");
                            setIssuesListPage(1);
                          }}
                          className={`rounded-lg px-2 py-0.5 text-xs font-semibold transition-all cursor-pointer ${
                            pageFilter === "all"
                              ? "bg-sky-700 text-white shadow-2xs dark:bg-sky-600"
                              : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
                          }`}
                        >
                          All ({allFindings.length})
                        </button>

                        {/* Page Chips Pagination Stepper (1-10 per view) */}
                        {totalChipsPages > 1 && (
                          <div className="flex items-center gap-0.5 shrink-0 px-1 py-0.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                            <button
                              type="button"
                              disabled={safeChipsPage <= 1}
                              onClick={() => setPageChipsPage((p) => Math.max(1, p - 1))}
                              className="rounded p-0.5 text-slate-600 dark:text-slate-300 disabled:opacity-30 hover:bg-white dark:hover:bg-slate-700 cursor-pointer"
                              title="Previous 10 pages"
                              aria-label="Previous 10 pages"
                            >
                              <ChevronLeft className="h-3 w-3" />
                            </button>
                            <span className="text-[10px] font-mono font-bold text-slate-600 dark:text-slate-300 px-1">
                              {safeChipsPage}/{totalChipsPages}
                            </span>
                            <button
                              type="button"
                              disabled={safeChipsPage >= totalChipsPages}
                              onClick={() => setPageChipsPage((p) => Math.min(totalChipsPages, p + 1))}
                              className="rounded p-0.5 text-slate-600 dark:text-slate-300 disabled:opacity-30 hover:bg-white dark:hover:bg-slate-700 cursor-pointer"
                              title="Next 10 pages"
                              aria-label="Next 10 pages"
                            >
                              <ChevronRight className="h-3 w-3" />
                            </button>
                          </div>
                        )}

                        {visibleChangedPages.map((pageNum) => {
                          const pageIssues = allFindings.filter((item) => findingOnPdfPage(item, pageNum));
                          const isSelected = pageFilter === pageNum;
                          const hasError = pageIssues.some((item) => item.severity === "error");
                          const isReviewed = reviewedPages.has(pageNum);
                          return (
                            <button
                              key={pageNum}
                              type="button"
                              onClick={() => {
                                setPageFilter(pageNum);
                                setActivePreviewPage(pageNum);
                                setIssuesListPage(1);
                                const firstIdx = allFindings.findIndex((item) => findingOnPdfPage(item, pageNum));
                                if (firstIdx !== -1) setSelected(firstIdx);
                              }}
                              className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-0.5 font-mono text-xs font-bold transition-all cursor-pointer ${
                                isSelected
                                  ? "bg-sky-600 text-white shadow-2xs ring-2 ring-sky-400/50"
                                  : isReviewed
                                  ? "border border-emerald-300 bg-emerald-50 text-emerald-800 hover:bg-emerald-100 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
                                  : hasError
                                  ? "border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300"
                                  : "border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300"
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={isReviewed}
                                onChange={(e) => {
                                  e.stopPropagation();
                                  togglePageReviewed(pageNum);
                                }}
                                onClick={(e) => e.stopPropagation()}
                                className="h-3 w-3 rounded text-sky-600 focus:ring-0 cursor-pointer accent-sky-600"
                                title={`Mark Page ${pageNum} as reviewed`}
                                aria-label={`Mark Page ${pageNum} as reviewed`}
                              />
                              <span className={`h-1.5 w-1.5 rounded-full ${isSelected ? "bg-white" : isReviewed ? "bg-emerald-500" : hasError ? "bg-rose-500" : "bg-amber-500"}`} />
                              <span>p. {pageNum}</span>
                              <span className={`text-[10px] ${isSelected ? "text-white" : "opacity-75"}`}>({pageIssues.length})</span>
                            </button>
                          );
                        })}
                      </div>
                    )}

                    {(issueFilter !== "all" || pageFilter !== "all" || issueSearch) && (
                      <div className="flex items-center justify-between text-[11px] text-slate-500">
                        <span>
                          Showing {filteredFindings.length} of {allFindings.length} issues
                          {pageFilter !== "all" && ` on Page ${pageFilter}`}
                        </span>
                        <button
                          type="button"
                          onClick={() => {
                            setIssueFilter("all");
                            setPageFilter("all");
                            setIssueSearch("");
                          }}
                          className="font-semibold text-sky-600 hover:underline dark:text-sky-400 cursor-pointer"
                        >
                          Clear filter
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {result.findings_truncated && (
                  <p className="text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 p-2 rounded-lg border border-amber-200 dark:border-amber-800">
                    Showing the first 100 content findings. Review the whole document.
                  </p>
                )}

                {/* Empty State when no issues found */}
                {result.findings.length === 0 && (
                  <div className={`rounded-xl border p-4 text-center ${result.status === "match"
                    ? "border-emerald-200/70 bg-emerald-50/50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-200"
                    : "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"}`}>
                    {result.status === "match" ? <CheckCircle2 className="mx-auto mb-1.5 h-7 w-7" /> : <Info className="mx-auto mb-1.5 h-7 w-7" />}
                    <p className="text-xs sm:text-sm font-bold">
                      {result.status === "match" ? "No content issues detected" : "No comparison findings available"}
                    </p>
                    <p className="mt-0.5 text-xs">
                      {result.status === "match" ? "The document matched the source within the verified scope." : "Read the validation summary and coverage before accepting this file."}
                    </p>
                  </div>
                )}

                {/* Empty State when filter yields 0 matches */}
                {allFindings.length > 0 && filteredFindings.length === 0 && (
                  <div className="rounded-xl border border-dashed border-slate-200 p-4 text-center text-xs text-slate-500 dark:border-slate-700">
                    <p className="font-semibold">No issues match the selected filter</p>
                    <button
                      type="button"
                      onClick={() => {
                        setIssueFilter("all");
                        setIssueSearch("");
                      }}
                      className="mt-2 inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 shadow-2xs hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 cursor-pointer"
                    >
                      Reset filters
                    </button>
                  </div>
                )}

                {/* Issues selector list with Checkboxes & Pagination (1-10) */}
                {filteredFindings.length > 0 && (
                  <div className="space-y-2">
                    <div className="max-h-60 space-y-1.5 overflow-y-auto pr-1">
                      {paginatedFindings.map((item) => {
                        const originalIndex = allFindings.indexOf(item);
                        const isSelected = selected === originalIndex;
                        const isReviewed = reviewedIssues.has(originalIndex);
                        return (
                          <div
                            key={originalIndex}
                            role="button"
                            tabIndex={0}
                            aria-pressed={isSelected}
                            onClick={() => {
                              setSelected(originalIndex);
                              if (item.pdf_page) setActivePreviewPage(item.pdf_page);
                            }}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                setSelected(originalIndex);
                                if (item.pdf_page) setActivePreviewPage(item.pdf_page);
                              }
                            }}
                            className={`w-full rounded-xl border p-2.5 text-left text-xs transition-all cursor-pointer flex items-start gap-2.5 ${
                              isSelected
                                ? "border-sky-400 bg-sky-50 dark:bg-sky-950/40 shadow-xs ring-1 ring-sky-400/30"
                                : isReviewed
                                ? "border-emerald-200/80 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/20 hover:bg-emerald-50/60"
                                : "border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/60"
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={isReviewed}
                              onChange={(e) => {
                                e.stopPropagation();
                                toggleIssueReviewed(originalIndex);
                              }}
                              onClick={(e) => e.stopPropagation()}
                              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500 cursor-pointer shrink-0 accent-sky-600"
                              title="Mark issue as reviewed"
                              aria-label={`Mark issue on ${findingPageLabel(item)} as reviewed`}
                            />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-1.5 min-w-0">
                                  <span className={isReviewed ? "line-through text-slate-500 dark:text-slate-400" : ""}>
                                    {findingPageLabel(item)}
                                  </span>
                                  {item.source_heading && (
                                    <span className="text-[10px] font-normal text-slate-500 truncate max-w-[180px]">
                                      • {item.source_heading}
                                    </span>
                                  )}
                                  {isReviewed && (
                                    <span className="inline-flex items-center text-[10px] font-bold text-emerald-700 dark:text-emerald-300 bg-emerald-100 dark:bg-emerald-900/60 px-1.5 py-0.2 rounded border border-emerald-200 dark:border-emerald-800">
                                      Reviewed
                                    </span>
                                  )}
                                </span>
                                <span
                                  className={`text-[10px] uppercase font-mono font-bold px-1.5 py-0.5 rounded shrink-0 ${
                                    item.severity === "error"
                                      ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
                                      : item.severity === "warning"
                                      ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                                      : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                                  }`}
                                >
                                  {item.severity}
                                </span>
                              </div>
                              <span className={`mt-0.5 block text-slate-700 dark:text-slate-300 line-clamp-2 ${isReviewed ? "text-slate-400 dark:text-slate-500" : ""}`}>
                                {item.message}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    {/* Pagination List of Pages (1-10) */}
                    {totalIssuePages > 1 && (
                      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-100 dark:border-slate-800 text-xs">
                        <div className="text-[11px] text-slate-500 dark:text-slate-400">
                          <span>
                            Showing <strong>{(safeIssuePage - 1) * ISSUES_PER_PAGE + 1}–{Math.min(safeIssuePage * ISSUES_PER_PAGE, filteredFindings.length)}</strong> of <strong>{filteredFindings.length}</strong>
                          </span>
                          <span className="ml-1.5 font-semibold text-emerald-600 dark:text-emerald-400">
                            • {reviewedIssues.size}/{allFindings.length} reviewed
                          </span>
                        </div>

                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            disabled={safeIssuePage <= 1}
                            onClick={() => setIssuesListPage((p) => Math.max(1, p - 1))}
                            className="inline-flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white px-2 py-0.5 text-xs font-medium text-slate-700 shadow-2xs hover:bg-slate-50 disabled:opacity-30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 cursor-pointer"
                            aria-label="Previous page"
                          >
                            <ChevronLeft className="h-3 w-3" />
                            <span className="hidden sm:inline">Prev</span>
                          </button>

                          <div className="flex items-center gap-1">
                            {Array.from({ length: Math.min(10, totalIssuePages) }).map((_, i) => {
                              const pNum = i + 1;
                              return (
                                <button
                                  key={pNum}
                                  type="button"
                                  onClick={() => setIssuesListPage(pNum)}
                                  className={`h-6 w-6 rounded-md text-[11px] font-bold transition-all cursor-pointer ${
                                    safeIssuePage === pNum
                                      ? "bg-sky-600 text-white shadow-2xs"
                                      : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
                                  }`}
                                  aria-label={`Page ${pNum}`}
                                  aria-current={safeIssuePage === pNum ? "page" : undefined}
                                >
                                  {pNum}
                                </button>
                              );
                            })}
                            {totalIssuePages > 10 && <span className="px-1 text-slate-400 font-mono text-xs">...</span>}
                          </div>

                          <button
                            type="button"
                            disabled={safeIssuePage >= totalIssuePages}
                            onClick={() => setIssuesListPage((p) => Math.min(totalIssuePages, p + 1))}
                            className="inline-flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white px-2 py-0.5 text-xs font-medium text-slate-700 shadow-2xs hover:bg-slate-50 disabled:opacity-30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 cursor-pointer"
                            aria-label="Next page"
                          >
                            <span className="hidden sm:inline">Next</span>
                            <ChevronRight className="h-3 w-3" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Selected finding detail inspector with word-level diffing */}
                {finding && (
                  <PdfFindingDiffInspector
                    finding={finding}
                    onJumpToPdfPage={(targetPage) => {
                      setActivePreviewPage(targetPage);
                      document.getElementById("uploaded-pdf-preview")?.scrollIntoView({ behavior: "smooth", block: "start" });
                    }}
                  />
                )}
              </section>

              {/* Column 2: Uploaded PDF Preview Panel */}
              <PdfValidationPreview
                active={active}
                preview={preview}
                page={previewPage}
                totalPages={result.pdf_pages}
                findings={allFindings}
                selectedFindingIndex={selected}
                onSelectFinding={(idx) => {
                  setSelected(idx);
                }}
                onPageChange={(newPage) => setActivePreviewPage(newPage)}
                filename={file?.name} file={file}
                className={PANEL}
              />
            </div>
          </>
        )}
      </>
    )}
  </div>
</div>
);
}
