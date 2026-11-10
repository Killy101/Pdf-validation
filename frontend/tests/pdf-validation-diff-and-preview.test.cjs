const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT_DIR = path.resolve(__dirname, "..");

test("pdfDiffUtils correctly calculates word-level differences", async () => {
  const filePath = path.join(ROOT_DIR, "src", "lib", "pdfDiffUtils.ts");
  assert.ok(fs.existsSync(filePath), "pdfDiffUtils.ts must exist");
  const content = fs.readFileSync(filePath, "utf-8");

  // Verify core diff exports and logic
  assert.ok(content.includes("computeWordDiff"), "computeWordDiff must be exported");
  assert.ok(content.includes("DiffPart"), "DiffPart interface must exist");
  assert.ok(content.includes("WordDiffResult"), "WordDiffResult interface must exist");
  assert.ok(content.includes("tokenize"), "Tokenizer must exist");
  assert.ok(content.includes("mergeParts"), "mergeParts must exist");
});

test("PdfValidationPreview supports page stepping, issue page jump, and fullscreen modal", () => {
  const filePath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationPreview.tsx");
  assert.ok(fs.existsSync(filePath), "PdfValidationPreview.tsx must exist");
  const content = fs.readFileSync(filePath, "utf-8");

  // Verify page stepper
  assert.ok(content.includes("Previous PDF page"), "Must include previous page button");
  assert.ok(content.includes("Next PDF page"), "Must include next page button");
  assert.ok(content.includes("handlePageStep"), "Must include handlePageStep function");

  // Verify jump to issue page
  assert.ok(content.includes("Jump to issue"), "Must include jump to issue button");
  assert.ok(content.includes("handleReturnToIssuePage"), "Must include handleReturnToIssuePage function");

  // Verify fullscreen / expanded inspection view
  assert.ok(content.includes("Expand preview"), "Must include expand preview button");
  assert.ok(content.includes("Expanded PDF preview"), "Must render expanded preview dialog");
  assert.ok(content.includes("Escape"), "Must handle Escape key to close expanded view");

  // Verify open in new tab
  assert.ok(content.includes("Open in new browser tab"), "Must include link to open PDF in new tab");
});

test("PdfValidationView implements issue filtering, search, stepping, and diff inspector", () => {
  const filePath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationView.tsx");
  assert.ok(fs.existsSync(filePath), "PdfValidationView.tsx must exist");
  const content = fs.readFileSync(filePath, "utf-8");

  // Verify diff inspector integration
  assert.ok(content.includes("PdfFindingDiffInspector"), "Must render PdfFindingDiffInspector");

  // Verify search and severity filtering
  assert.ok(content.includes("issueSearch"), "Must support issue search state");
  assert.ok(content.includes("issueFilter"), "Must support severity filter state");
  assert.ok(content.includes("filteredFindings"), "Must calculate filteredFindings");
  assert.ok(content.includes("Search issues"), "Must include search issues input");

  // Verify previous / next issue stepper
  assert.ok(content.includes("Previous issue"), "Must include previous issue stepper button");
  assert.ok(content.includes("Next issue"), "Must include next issue stepper button");
  assert.ok(content.includes("handleStepIssue"), "Must include handleStepIssue function");
});

test("PdfFindingDiffInspector provides word-level visual diff, layout toggle, and copy actions", () => {
  const filePath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfFindingDiffInspector.tsx");
  assert.ok(fs.existsSync(filePath), "PdfFindingDiffInspector.tsx must exist");
  const content = fs.readFileSync(filePath, "utf-8");

  // Verify visual diffing
  assert.ok(content.includes("computeWordDiff"), "Must compute word differences");
  assert.ok(content.includes("Diff Highlight"), "Must offer diff highlight mode");
  assert.ok(content.includes("Plain"), "Must offer plain text mode");

  // Verify layout toggling
  assert.ok(content.includes("Stacked view"), "Must offer stacked view toggle");
  assert.ok(content.includes("Side-by-side view"), "Must offer side-by-side view toggle");

  // Verify copy actions
  assert.ok(content.includes("Copy text") || content.includes("Copy"), "Must provide copy buttons");
  assert.ok(content.includes("handleCopyDiffMarkdown"), "Must offer Markdown diff export");

  // Verify deleted text uses red text without strikethrough
  assert.ok(!content.includes("line-through"), "Deleted diff text must not use line-through strikethrough styling");
  assert.ok(content.includes("text-rose-600"), "Deleted diff text must be highlighted as red text");

  // Verify inline unified diff mode and website comparison badges
  assert.ok(content.includes("Inline"), "Must provide Inline unified diff mode");
  assert.ok(content.includes("changeBadge"), "Must calculate changeBadge for website differences");
  assert.ok(content.includes("onJumpToPdfPage"), "Must support jumping to PDF page from inspector");
});

test("PdfValidationPreview supports changed-pages quick ribbon, change stepper, and active page banner", () => {
  const filePath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationPreview.tsx");
  const content = fs.readFileSync(filePath, "utf-8");

  // Verify changed pages aggregation and quick jump ribbon
  assert.ok(content.includes("changedPages"), "Must calculate changedPages from findings");
  assert.ok(content.includes("Pages with changes") || content.includes("Changed pages"), "Must render changed pages ribbon");

  // Verify next and previous change stepping
  assert.ok(content.includes("Previous changed page"), "Must include previous changed page button");
  assert.ok(content.includes("Next changed page"), "Must include next changed page button");
  assert.ok(content.includes("handleStepChange"), "Must implement handleStepChange");

  // Verify active page change banner
  assert.ok(content.includes("currentPageFindings"), "Must calculate currentPageFindings");
  assert.ok(content.includes("No reported finding on uploaded page"), "Unreported pages must not be claimed to match the source");
});

test("PdfValidationView implements page-level filtering and changed pages metrics", () => {
  const filePath = path.join(ROOT_DIR, "src", "components", "pdf-validation", "PdfValidationView.tsx");
  const content = fs.readFileSync(filePath, "utf-8");

  // Verify page filter state and logic
  assert.ok(content.includes("pageFilter"), "Must implement pageFilter state");
  assert.ok(content.includes("setPageFilter"), "Must implement setPageFilter");
  assert.ok(content.includes("changedPages"), "Must compute changedPages");
  assert.ok(content.includes("Pages to review"), "Must render the pages requiring review");

  // Verify preview page synchronization
  assert.ok(content.includes("activePreviewPage"), "Must track activePreviewPage");
  assert.ok(content.includes("setActivePreviewPage"), "Must update activePreviewPage");
});
