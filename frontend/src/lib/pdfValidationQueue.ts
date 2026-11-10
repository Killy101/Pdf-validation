import { ApiError } from "./api";
import { createPdfValidationBatch, releasePdfValidationBatch, PdfValidationConfiguration, PdfValidationOptions, PdfValidationResult, validatePdf } from "./pdfValidation";

export interface PdfQueueItem {
  state: "pending" | "processing" | "done" | "error" | "cancelled";
  result?: PdfValidationResult;
  error?: string;
}

export function checkPdfFiles(files: File[], configuration: PdfValidationConfiguration) {
  const limit = Math.min(configuration.max_files ?? 10, 10);
  if (!files.length || files.length > limit) throw new Error(`Choose between 1 and ${limit} PDF files.`);
  for (const file of files) {
    if (!/\.pdf$/i.test(file.name)) throw new Error(`${file.name}: Choose a PDF file.`);
    if (file.size > configuration.max_upload_bytes) throw new Error(`${file.name} exceeds the upload limit shown below.`);
  }
}

export async function validatePdfQueue(
  files: File[], contentUri: string, referenceUrl: string | undefined,
  configuration: PdfValidationConfiguration, signal: AbortSignal,
  onUpdate: (index: number, item: PdfQueueItem) => void,
  options: PdfValidationOptions = {}
) {
  checkPdfFiles(files, configuration);
  if (signal.aborted) return "cancelled";
  let batchId: string;
  try {
    batchId = await createPdfValidationBatch(contentUri, referenceUrl, signal, options);
  } catch (error) {
    if (signal.aborted) return "cancelled";
    throw error;
  }
  try {
    for (let index = 0; index < files.length; index++) {
      if (signal.aborted) return "cancelled";
      onUpdate(index, { state: "processing" });
      if (signal.aborted) return "cancelled";
      try {
        const result = await validatePdf(files[index], contentUri, referenceUrl, signal, options, batchId);
        if (signal.aborted) return "cancelled";
        onUpdate(index, { state: "done", result });
        if (result.source_access_issue) return "source_unavailable";
        if (result.workflow === "date_range" && !result.versions?.length) return "history_unavailable";
        if (result.comparison === "not_checked" && result.references.length
          && (!referenceUrl || result.references.some(item => item.archive_member) && !options.archive_member)) return "reference_required";
      } catch (error) {
        if (signal.aborted) return "cancelled";
        onUpdate(index, { state: "error", error: error instanceof Error ? error.message : "Validation failed. Try again." });
        if (error instanceof ApiError && [401, 403, 409, 429, 503].includes(error.status)) return "stopped";
      }
    }
    return "complete";
  } finally {
    void releasePdfValidationBatch(batchId).catch(() => {});
  }
}
