import { ApiError, apiRequest } from "./api";

export const PDF_JURISDICTIONS = {
  auto: "Auto detect", au: "Australia", ca: "Canada", kr: "South Korea", uk: "United Kingdom",
  us: "United States", nz: "New Zealand", jp: "Japan", sg: "Singapore", eu: "European Union", other: "Other jurisdiction"
};

export interface PdfValidationOptions {
  workflow?: "current" | "date_range";
  date_start?: string;
  date_end?: string;
  history_url?: string;
  archive_member?: string;
  // content: the URL is the document. reference: a landing page the document is found from.
  source_mode?: PdfSourceMode;
}

export type PdfSourceMode = "content" | "reference";

export function checkPdfScope(options: PdfValidationOptions) {
  if (options.workflow !== "date_range") return;
  if (!options.date_start || !options.date_end) throw new Error("Choose both From date and To date.");
  for (const date of [options.date_start, options.date_end]) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date))
      || new Date(date).toISOString().slice(0, 10) !== date) throw new Error("Choose valid comparison dates.");
  }
  if (options.date_start > options.date_end) throw new Error("From date must be on or before To date.");
}

function scopeFields(options: PdfValidationOptions) {
  checkPdfScope(options);
  return { workflow: options.workflow ?? "current",
    ...(options.source_mode === "reference" ? { source_mode: "reference" } : {}),
    ...(options.archive_member ? { archive_member: options.archive_member } : {}),
    ...(options.workflow === "date_range" ? { date_start: options.date_start, date_end: options.date_end,
      ...(options.history_url?.trim() ? { history_url: options.history_url.trim() } : {}) } : {}) };
}

function checkWorkflowResponse<T extends { workflow?: string; source_mode?: string }>(result: T, options: PdfValidationOptions) {
  if (options.workflow === "date_range" && result.workflow !== "date_range") {
    throw new Error("The backend has not loaded date range support. Restart the backend and try again.");
  }
  if (options.source_mode === "reference" && "status" in result && result.source_mode !== "reference") {
    throw new Error("The running backend does not support Reference URL discovery. Close and reopen the app.");
  }
  return result;
}

export interface PdfReference {
  url: string;
  label: string;
  available: boolean;
  kind?: "pdf" | "html" | "zip";
  archive_member?: string | null;
}

export function pdfReferenceKey(reference: PdfReference) {
  return reference.archive_member ? JSON.stringify([reference.url, reference.archive_member]) : reference.url;
}

export interface PdfHistoricalReference extends PdfReference {
  valid_from: string;
  valid_to: string | null;
}

export interface PdfVersionComparison {
  reference: PdfHistoricalReference;
  result: PdfValidationResult;
}

export interface PdfFinding {
  kind: string;
  severity: "error" | "warning" | "info";
  message: string;
  pdf_page: number | null;
  pdf_page_end?: number | null;
  approximate_location: boolean;
  source_page: number | null;
  source_page_end?: number | null;
  source_heading: string | null;
  source_archive_member?: string | null;
  source_url: string;
  expected: string;
  actual: string;
  pdf_search_text?: string;
  excerpt_truncated?: boolean;
  expected_change?: [number, number] | null;
  actual_change?: [number, number] | null;
  action: string;
}

export interface PdfValidationResult {
  status: "match" | "mismatch" | "needs_review" | "unable";
  summary: string;
  comparison: "exact_file" | "content" | "not_checked";
  filename: string;
  submitted_url: string;
  source_url: string;
  source_type: "pdf" | "html" | "zip" | "unknown";
  archive_source?: { url: string; sha256: string; member: string; member_sha256: string; unsupported_members: string[] } | null;
  source_access_issue?: "captcha" | "access_denied" | "rate_limited" | "unavailable" | null;
  checked_at: string;
  upload_sha256: string;
  source_sha256: string | null;
  source_retrieved_at?: string | null;
  retrieval_attempts?: number;
  document_identity?: "match" | "mismatch" | "needs_review" | "not_checked";
  identity_summary?: string | null;
  identity_pdf_title?: string | null;
  identity_source_title?: string | null;
  comparison_language?: string;
  language_alignment?: "all_text" | "selected" | "needs_review";
  pdf_layout?: PdfLayoutEvidence | null;
  source_layout?: PdfLayoutEvidence | null;
  scope_notes?: string[];
  pdf_dates?: PdfDateEvidence | null;
  source_dates?: PdfDateEvidence | null;
  website_modified_on?: string | null;
  source_coverage?: PdfSourceCoverage | null;
  pdf_pages: number | null;
  source_pages: number | null;
  checked_pdf_pages: number;
  pdf_title: string | null;
  source_title: string | null;
  coverage_complete: boolean;
  findings_truncated: boolean;
  findings: PdfFinding[];
  references: PdfReference[];
  limitations: string[];
  jurisdiction?: keyof typeof PDF_JURISDICTIONS;
  workflow?: "current" | "date_range";
  date_start?: string | null;
  date_end?: string | null;
  history_complete?: boolean;
  versions?: PdfVersionComparison[];
  source_mode?: PdfSourceMode;
  discovery?: PdfDiscoveryTrail | null;
}

export interface PdfDiscoveryStep { url: string; label: string }

export type PdfDiscoveryStatus = "selected" | "verified" | "needs_verification" | "rejected" | "inaccessible" | "unavailable" | "visited" | "not_relevant";

export interface PdfDiscoveryItem {
  url: string;
  label: string;
  kind: "pdf" | "zip" | "html" | "other";
  status: PdfDiscoveryStatus;
  reason?: string | null;
  score?: number | null;
  depth?: number | null;
  path: PdfDiscoveryStep[];
}

export interface PdfDiscoveryTrail {
  start_url: string;
  status: "found" | "needs_review" | "not_found";
  summary: string;
  selected_url: string | null;
  selected_label: string | null;
  document_identity?: string | null;
  path: PdfDiscoveryStep[];
  pages_visited: number;
  browser_pages: number;
  items: PdfDiscoveryItem[];
  notes: string[];
}

export interface PdfLayoutEvidence {
  columns: number | null;
  languages: string[];
  parallel_bilingual?: boolean;
  column_languages?: string[];
}

export interface PdfSourceCoverage {
  method: string;
  expected_sections: number | null;
  retrieved_sections: number;
  pages_retrieved: number;
  complete: boolean;
  sections: {url: string; label: string; status: "retrieved" | "unavailable" | "not_checked"; reason?: string | null}[];
  notes: string[];
}

export interface PdfDateEvidence {
  current_to?: string | null;
  creation_date?: string | null;
  modification_date?: string | null;
}

export interface PdfValidationConfiguration {
  max_upload_bytes: number;
  max_files?: number;
  max_pages: number;
  timeout_seconds: number;
  max_versions?: number;
}

export interface PdfSourceDiscovery {
  source_url: string;
  source_type: "pdf" | "html" | "zip" | "unknown";
  source_title: string | null;
  summary: string;
  references: PdfReference[];
  jurisdiction?: keyof typeof PDF_JURISDICTIONS;
  workflow?: "current" | "date_range";
  history_complete?: boolean;
  versions?: PdfHistoricalReference[];
  limitations?: string[];
  source_mode?: PdfSourceMode;
  discovery?: PdfDiscoveryTrail | null;
}

// Finds the uploaded document inside the website that starts at a Reference URL.
export function discoverReferenceDocument(document: File, referenceUrl: string, signal?: AbortSignal) {
  const body = new FormData();
  body.append("document", document);
  body.append("content_uri", referenceUrl.trim());
  return apiRequest<PdfSourceDiscovery>("/pdf-validations/reference-discovery", { method: "POST", body, signal })
    .then(result => {
      if (result.source_mode !== "reference") throw new Error("The running backend does not support Reference URL discovery. Close and reopen the app.");
      return result;
    });
}

export const discoverPdfSource = (contentUri: string, signal?: AbortSignal, options: PdfValidationOptions = {}) =>
  apiRequest<PdfSourceDiscovery>("/pdf-validations/sources", {
    method: "POST", body: JSON.stringify({ content_uri: contentUri.trim(), ...scopeFields(options) }), signal
  }).then(result => checkWorkflowResponse(result, options));

export const fetchPdfValidationConfiguration = (signal?: AbortSignal) =>
  apiRequest<PdfValidationConfiguration>("/pdf-validations/configuration", { cache: "no-store", signal });

export async function createPdfValidationBatch(contentUri: string, referenceUrl?: string, signal?: AbortSignal,
  options: PdfValidationOptions = {}) {
  try {
    const result = await apiRequest<{ batch_id: string; expires_at: string }>("/pdf-validations/batches", {
      method: "POST", body: JSON.stringify({ content_uri: contentUri.trim(),
        ...(referenceUrl ? { reference_url: referenceUrl } : {}), ...scopeFields(options) }), signal
    });
    if (!/^[0-9a-f]{32}$/.test(result.batch_id ?? "")) {
      throw new Error("The backend has not loaded batch snapshot support. Restart the backend and try again.");
    }
    return result.batch_id;
  } catch (error) {
    if (error instanceof ApiError && [404, 405].includes(error.status)) {
      throw new Error("The backend has not loaded batch snapshot support. Restart the backend and try again.");
    }
    throw error;
  }
}

export const releasePdfValidationBatch = (batchId: string) =>
  apiRequest<void>(`/pdf-validations/batches/${batchId}`, { method: "DELETE" });

export function validatePdf(document: File, contentUri: string, referenceUrl?: string, signal?: AbortSignal,
  options: PdfValidationOptions = {}, batchId?: string) {
  const body = new FormData();
  body.append("document", document);
  body.append("content_uri", contentUri.trim());
  if (referenceUrl) body.append("reference_url", referenceUrl);
  if (batchId) body.append("batch_id", batchId);
  for (const [field, value] of Object.entries(scopeFields(options))) {
    if (value) body.append(field, value);
  }
  return apiRequest<PdfValidationResult>("/pdf-validations", { method: "POST", body, signal })
    .then(result => checkWorkflowResponse(result, options));
}

export interface PdfTextMatch { page: number; count: number; before: string; match: string; after: string }
export interface PdfTextSearchResult {
  query: string; pages_searched: number; pages_with_text: number; pages_matched: number;
  total_matches: number; truncated: boolean; matches: PdfTextMatch[];
}

// Finds wording in the uploaded PDF's text layer; the answer lists the pages that contain it.
export function searchPdfText(document: File, query: string, signal?: AbortSignal) {
  const body = new FormData();
  body.append("document", document);
  body.append("query", query);
  return apiRequest<PdfTextSearchResult>("/pdf-validations/search-text", { method: "POST", body, signal });
}
