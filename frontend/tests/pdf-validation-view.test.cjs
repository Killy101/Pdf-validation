const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT_DIR = path.resolve(__dirname, "..");

test("PdfValidationView separates upload form from results view and provides a new validation action", () => {
  const filePath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationView.tsx");
  assert.ok(fs.existsSync(filePath), "PdfValidationView.tsx should exist");
  const content = fs.readFileSync(filePath, "utf-8");

  // Verify view separation: upload form is shown when !showResults, results view is shown when showResults
  assert.ok(content.includes("!showResults"), "Upload form must only render when !showResults");
  assert.ok(content.includes("showResults"), "Results view must render when showResults");
  assert.ok(content.includes("PDF Validation Results"), "Dedicated results view heading must exist");

  // Verify the explicit new session action.
  assert.ok(content.includes("New PDF Validation"), "Must include 'New PDF Validation' button");
  assert.ok(content.includes("handleNewPdfValidation"), "Must have handleNewPdfValidation function");
  assert.ok(content.includes("setFiles([])") || content.includes("setFile"), "handleValidateAnotherPdf must reset file state");
  assert.ok(content.includes("setShowResults(false)") || content.includes("setResult(null)"), "handleValidateAnotherPdf must hide results");
  assert.ok(content.includes("setPreview"), "handleValidateAnotherPdf must reset preview state");

  // Verify new file selection requirement
  assert.ok(content.includes("disabled={!files.length") || content.includes("disabled={!file"), "Validate PDF button must be disabled when file is null");
});

test("PdfValidationView implements sidebar-adaptive responsive layout with side-by-side results on large screens", () => {
  const filePath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationView.tsx");
  const content = fs.readFileSync(filePath, "utf-8");

  // Verify fluid width that adapts to sidebar expand and collapse
  assert.ok(content.includes("w-full max-w-none"), "Inner container must be max-w-none to expand when sidebar collapses");
  assert.ok(!content.includes("max-w-7xl"), "Must not constrain layout to max-w-7xl");

  // Verify side-by-side on larger screens (lg:grid-cols-2) and stacked on smaller screens (grid-cols-1)
  assert.ok(content.includes("grid-cols-1 lg:grid-cols-2"), "Must use grid-cols-1 lg:grid-cols-2 for findings and PDF preview");
  assert.ok(content.includes("min-w-0"), "Panels must specify min-w-0 to prevent overflow");

  // Verify dedicated results view elements
  assert.ok(content.includes("Verdict"), "Must render verdict indicator");
  assert.ok(content.includes("Download report"), "Must render Download report action");
  assert.ok(content.includes("PdfValidationPreview"), "Must render PDF preview panel");
  assert.ok(content.includes("Issues to review"), "Must render Issues to review panel");
  assert.ok(content.includes("Scope Limitations"), "Must render Scope Limitations block");
});

test("PdfValidationView avoids duplicated action buttons, integrates PDF dropdown, and toggles Scope Limitations", () => {
  const filePath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationView.tsx");
  const content = fs.readFileSync(filePath, "utf-8");

  // Verify the new session action is available in the results view.
  const newValidationMatches = (content.match(/New PDF Validation/g) || []).length;
  assert.equal(newValidationMatches, 1, "Results view must provide the new validation action");

  const downloadReportMatches = (content.match(/Download report/g) || []).length;
  assert.equal(downloadReportMatches, 1, "There must be exactly one 'Download report' button instance");

  // Verify integrated file selector dropdown inside results view
  assert.ok(content.includes('id="validation-active-pdf"'), "Must include validation-active-pdf dropdown");

  // Verify toggleable Scope Limitations button in results actions
  assert.ok(content.includes("showLimitations"), "Must support showLimitations state");
  assert.ok(content.includes("setShowLimitations"), "Must support setShowLimitations toggle");
});

test("PdfValidationView shows details in a drawer and keeps downloads in the header next to Scope Limitations", () => {
  const filePath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationView.tsx");
  const content = fs.readFileSync(filePath, "utf-8");

  // The Details button opens the drawer, which owns the source/jurisdiction and comparison scope panels.
  assert.ok(content.includes("<span>Details</span>"), "Must render a Details button");
  assert.ok(content.includes("<PdfValidationDetailsDrawer"), "Must render the details drawer");
  assert.ok(content.includes("setShowDetails(true)") && content.includes("setShowDetails(false)"), "Must open and close the drawer");
  assert.ok(!content.includes("<PdfValidationEvidence"), "Comparison scope and dates must live in the drawer, not inline");
  assert.ok(!content.includes("Jurisdiction: "), "The Jurisdiction panel must live in the drawer, not inline");

  // Downloads render once, in the header action row between Scope Limitations and New PDF Validation.
  assert.equal((content.match(/<PdfValidationDownloads/g) || []).length, 1, "Downloads must be rendered exactly once");
  const limitations = content.indexOf("{/* Scope Limitations Button */}");
  const downloads = content.indexOf("<PdfValidationDownloads");
  const newValidation = content.indexOf("onClick={handleNewPdfValidation}");
  assert.ok(limitations > 0 && limitations < downloads && downloads < newValidation, "Downloads must sit next to Scope Limitations in the header");
});

test("PdfValidationView implements review checkboxes, 1-10 pagination, and eliminates redundant actions", () => {
  const viewPath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationView.tsx");
  const viewContent = fs.readFileSync(viewPath, "utf-8");

  // Checkbox review tracking
  assert.ok(viewContent.includes("reviewedIssues"), "Must maintain reviewedIssues state");
  assert.ok(viewContent.includes("toggleIssueReviewed"), "Must provide toggleIssueReviewed helper");
  assert.ok(viewContent.includes("reviewedPages"), "Must compute reviewedPages");
  assert.ok(viewContent.includes("togglePageReviewed"), "Must provide togglePageReviewed helper");
  assert.ok(viewContent.includes('title="Mark issue as reviewed"'), "Must render review checkbox for findings");
  assert.ok(viewContent.includes("Mark Page"), "Must render review checkbox for pages");

  // Pagination 1-10
  assert.ok(viewContent.includes("ISSUES_PER_PAGE = 10"), "Must paginate findings by 10");
  assert.ok(viewContent.includes("paginatedFindings"), "Must slice findings for active page");
  assert.ok(viewContent.includes("totalIssuePages"), "Must compute totalIssuePages");

  // Redundant actions removed from Diff Inspector
  const diffPath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfFindingDiffInspector.tsx");
  const diffContent = fs.readFileSync(diffPath, "utf-8");
  assert.ok(!diffContent.includes("View PDF page"), "Redundant 'View PDF page' button must be removed from diff inspector");

  // Redundant actions removed from Preview
  const previewPath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationPreview.tsx");
  const previewContent = fs.readFileSync(previewPath, "utf-8");
  assert.ok(!previewContent.includes("Pages with changes"), "Redundant 'Pages with changes' ribbon must be removed from preview");
  assert.ok(!previewContent.includes("Inspect diff"), "Redundant 'Inspect diff' button must be removed from preview");
});

test("PdfValidationView offers Content URI and Reference URL modes and shows the discovery path", () => {
  const view = fs.readFileSync(path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationView.tsx"), "utf-8");
  assert.ok(view.includes('role="radiogroup"') && view.includes("Content URI") && view.includes("Reference URL"));
  assert.ok(view.includes("discoverReferenceDocument") && view.includes("Find this PDF on the website"));
  assert.ok(view.includes('source_mode: "reference"'), "Reference mode must be sent to the backend");
  assert.ok(view.includes("<PdfDiscoveryPath trail={result.discovery} compact />"), "The verdict shows the compact discovery path");
  const api = fs.readFileSync(path.join(ROOT_DIR, "src", "lib", "pdfValidation.ts"), "utf-8");
  assert.ok(api.includes("/pdf-validations/reference-discovery"));
});
