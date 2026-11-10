import { apiDownload } from "./api";
import type { PdfValidationResult } from "./pdfValidation";

export type PdfDownloadKind = "official" | "updated";

export function pdfDownloadAvailability(result: PdfValidationResult, hasUpload: boolean) {
  const checked = result.comparison !== "not_checked" && Boolean(result.source_sha256) && !result.source_access_issue;
  return {
    official: checked && result.source_type === "pdf",
    updated: checked && hasUpload && result.coverage_complete && result.document_identity === "match"
  };
}

export function pdfDownloadFilename(result: PdfValidationResult, kind: PdfDownloadKind) {
  let filename = result.filename;
  if (kind === "official") {
    try { filename = result.archive_source?.member.split("/").pop() || decodeURIComponent(new URL(result.source_url).pathname.split("/").pop() || "source-document.pdf"); }
    catch { filename = "source-document.pdf"; }
  }
  const stem = filename.replace(/\.pdf$/i, "").replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^[.-]+|[.-]+$/g, "").slice(0, 120) || "document";
  return `${stem}${kind === "updated" ? "-updated" : ""}.pdf`;
}

export async function fetchValidationPdf(result: PdfValidationResult, kind: PdfDownloadKind, file?: File, signal?: AbortSignal) {
  if (!pdfDownloadAvailability(result, Boolean(file))[kind]) throw new Error("This PDF download is unavailable. Review the document identity and coverage.");
  const fields = {source_url: result.source_url, source_sha256: result.source_sha256!,
    ...(result.archive_source ? {archive_member: result.archive_source.member, archive_sha256: result.archive_source.sha256} : {})};
  let blob: Blob;
  if (kind === "official") {
    blob = await apiDownload(`/pdf-validations/source-pdf?${new URLSearchParams(fields)}`, signal);
  } else {
    const body = new FormData();
    body.append("document", file!);
    for (const [key, value] of Object.entries(fields)) body.append(key, value);
    blob = await apiDownload("/pdf-validations/updated-pdf", signal, {method: "POST", body});
  }
  if (await blob.slice(0, 5).text() !== "%PDF-") throw new Error("The download did not return a PDF. Restart the backend and validate again.");
  return blob;
}
