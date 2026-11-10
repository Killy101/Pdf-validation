import type { PdfSourceCoverage as Coverage } from "@/lib/pdfValidation";

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

// States precisely which declared sections were not compared, so "incomplete" is never a blanket claim.
export function coverageMessage(coverage: Coverage) {
  if (coverage.complete) return "Declared source sections were retrieved. Check the comparison scope before accepting.";
  const unavailable = coverage.sections.filter(section => section.status === "unavailable").length;
  const unchecked = coverage.sections.filter(section => section.status === "not_checked").length;
  const parts = [unavailable && `${plural(unavailable, "section")} could not be retrieved`,
    unchecked && `${plural(unchecked, "section")} ${unchecked === 1 ? "was" : "were"} not checked`].filter(Boolean);
  if (parts.length) return `Source collection is incomplete: ${parts.join(" and ")}. Differences in those sections are not reported.`;
  if (coverage.expected_sections === null) return "Source collection is incomplete: the section limit was reached, so later sections were not checked.";
  return "Source collection is incomplete: some document content is interactive or partly loaded and needs manual review.";
}

export function PdfSourceCoverage({coverage}: {coverage?: Coverage | null}) {
  if (!coverage) return null;
  return <section aria-label="Source collection coverage" className="space-y-3 rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-700">
    <h3 className="font-semibold">Source collection coverage</h3>
    <p>{coverage.retrieved_sections} / {coverage.expected_sections ?? "Unknown"} source sections retrieved across {coverage.pages_retrieved} page{coverage.pages_retrieved === 1 ? "" : "s"}.</p>
    <p className={coverage.complete ? "text-slate-600 dark:text-slate-300" : "text-amber-800 dark:text-amber-300"}>
      {coverageMessage(coverage)}
    </p>
    {coverage.method === "submitted_page" && <p className="text-xs text-slate-600 dark:text-slate-400">Only the submitted page was declared for this comparison. No linked document manifest was found.</p>}
    {coverage.method === "browser" && <p className="text-xs text-slate-600 dark:text-slate-400">Document content was collected using browser rendering.</p>}
    <details>
      <summary className="cursor-pointer font-medium">View collected and unchecked sections</summary>
      <ul className="mt-2 max-h-64 space-y-2 overflow-auto text-xs">
        {coverage.sections.map(section => <li key={section.url} className="rounded-lg border border-slate-100 p-2 dark:border-slate-800">
          <span className="font-semibold">{section.label}</span>{" - "}
          <span>{section.status === "retrieved" ? "Retrieved" : section.status === "unavailable" ? "Could not be retrieved" : "Not checked"}</span>
          {section.status === "retrieved" && <a href={section.url} target="_blank" rel="noopener noreferrer" className="ml-2 text-sky-700 underline dark:text-sky-300">Open source section</a>}
          {section.reason && <p className="mt-1">{section.reason}</p>}
        </li>)}
      </ul>
    </details>
    {coverage.notes.map(note => <p key={note} className="text-xs text-slate-600 dark:text-slate-400">{note}</p>)}
  </section>;
}
