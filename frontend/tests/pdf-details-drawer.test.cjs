const {test} = require('node:test');
const assert = require('node:assert/strict');
const {renderToStaticMarkup} = require('react-dom/server');
const React = require('react');

const {load} = require('./load-module.cjs');

const languages = load('src/lib/pdfLanguage.ts');
const evidence = load('src/components/pdf-validation/PdfValidationEvidence.tsx', {'@/lib/pdfLanguage': languages});
const library = {PDF_JURISDICTIONS: {us: 'United States', ca: 'Canada'}};
const discovery = load('src/components/pdf-validation/PdfDiscoveryTrail.tsx');
const {coverageMessage} = load('src/components/pdf-validation/PdfSourceCoverage.tsx');
const {PdfValidationDetailsDrawer, PdfSourceDetails} = load('src/components/pdf-validation/PdfValidationDetailsDrawer.tsx', {
  '@/lib/pdfValidation': library, './PdfValidationEvidence': evidence, './PdfDiscoveryTrail': discovery,
});
const start = {url: 'https://legislature.example/statutes/', label: 'Reference URL'};
const title = {url: 'https://legislature.example/statutes/4/title4ch0sec0.html', label: 'TITLE 4: JUDICIARY'};
const pdf = {url: 'https://legislature.example/statutes/4/title4.pdf', label: 'Title 4 PDF'};
const trail = {
  start_url: start.url, status: 'found', summary: 'Found the document on the website.', selected_url: pdf.url, selected_label: pdf.label,
  path: [start, title, pdf], pages_visited: 3, browser_pages: 0, document_identity: 'Title 4', notes: [],
  items: [
    {url: pdf.url, label: pdf.label, kind: 'pdf', status: 'selected', reason: 'Text matches the uploaded PDF.', path: [start, title, pdf]},
    {url: 'https://legislature.example/statutes/5/title5.pdf', label: 'Title 5 PDF', kind: 'pdf', status: 'rejected', reason: 'A different title.', path: [start]},
    {url: 'https://legislature.example/statutes/9/title9.pdf', label: 'Title 9 PDF', kind: 'pdf', status: 'unavailable', reason: 'HTTP 404', path: [start]},
  ],
};
const {PdfValidationDownloads} = load('src/components/pdf-validation/PdfValidationDownloads.tsx', {
  '@/lib/pdfLanguage': languages,
  '@/lib/pdfValidationDownloads': {pdfDownloadAvailability: () => ({official: true, updated: true}), fetchValidationPdf: async () => new Blob(), pdfDownloadFilename: () => 'a.pdf'},
});

const report = {
  filename: 'title4.pdf', jurisdiction: 'us', document_identity: 'match', source_title: 'MRS Title 4. JUDICIARY',
  source_url: 'https://legislature.example/statutes/4/title4.pdf', source_retrieved_at: '2026-11-10T03:28:25Z', retrieval_attempts: 1,
  pdf_layout: {columns: 1, languages: ['en']}, source_layout: {columns: 1, languages: ['en']},
  pdf_dates: {current_to: null}, source_dates: {current_to: null}, comparison: 'text', comparison_language: 'en', source_sha256: 'a'.repeat(64),
};

test('the details drawer renders nothing until it is opened', () => {
  assert.equal(renderToStaticMarkup(React.createElement(PdfValidationDetailsDrawer, {result: report, open: false, onClose() {}})), '');
});

test('the open drawer is a labelled dialog with the jurisdiction panel and the comparison scope and dates', () => {
  const html = renderToStaticMarkup(React.createElement(PdfValidationDetailsDrawer, {result: report, open: true, onClose() {}}));
  assert.ok(html.includes('role="dialog"') && html.includes('aria-modal="true"') && html.includes('aria-labelledby="pdf-details-title"'));
  assert.ok(html.includes('aria-label="Close details"'));
  assert.ok(html.includes('Jurisdiction: ') && html.includes('United States'));
  assert.ok(html.includes('Document identity: ') && html.includes('MRS Title 4. JUDICIARY') && html.includes(report.source_url));
  assert.ok(html.includes('Comparison scope and dates') && html.includes('Uploaded PDF layout') && html.includes('Source document current to'));
});

test('source details leave out rows the result does not have', () => {
  const html = renderToStaticMarkup(React.createElement(PdfSourceDetails, {result: {...report, jurisdiction: null, source_title: null, document_identity: 'needs_review'}}));
  assert.ok(!html.includes('Jurisdiction:') && !html.includes('Document identity:') && !html.includes('Source document:'));
  assert.ok(html.includes(report.source_url));
});

test('the drawer shows the Reference URL navigation path and groups what was checked', () => {
  const html = renderToStaticMarkup(React.createElement(PdfValidationDetailsDrawer, {
    result: {...report, source_mode: 'reference', submitted_url: start.url, discovery: trail}, open: true, onClose() {},
  }));
  assert.ok(html.includes('Reference URL: ') && html.includes('aria-label="Navigation path"'));
  assert.ok(html.includes('TITLE 4: JUDICIARY') && html.includes('Title 4 PDF') && html.includes('Document found'));
  assert.ok(html.includes('Discovered document (1)') && html.includes('Checked: a different document (1)') && html.includes('Unavailable (1)'));
  assert.ok(!renderToStaticMarkup(React.createElement(PdfValidationDetailsDrawer, {result: report, open: true, onClose() {}})).includes('Navigation path'));
});

test('the compact trail keeps the path and leaves out the grouped lists', () => {
  const html = renderToStaticMarkup(React.createElement(discovery.PdfDiscoveryPath, {trail: {...trail, status: 'not_found', selected_url: null, path: []}, compact: true}));
  assert.ok(html.includes('Document not found') && html.includes('Reference URL') && html.includes('Opened 3 pages'));
  assert.ok(!html.includes('Unavailable (1)'));
});

test('the coverage message says exactly what was not compared', () => {
  const section = (status) => ({url: `https://e.example/${status}`, label: status, status, reason: null});
  const base = {complete: false, expected_sections: 3, retrieved_sections: 1, pages_retrieved: 1, method: 'manifest', notes: []};
  assert.match(coverageMessage({...base, complete: true, sections: []}), /were retrieved/);
  assert.equal(coverageMessage({...base, sections: [section('retrieved'), section('unavailable'), section('not_checked')]}),
    'Source collection is incomplete: 1 section could not be retrieved and 1 section was not checked. Differences in those sections are not reported.');
  assert.match(coverageMessage({...base, sections: [section('retrieved'), section('unavailable'), section('unavailable')]}), /2 sections could not be retrieved\. /);
  assert.doesNotMatch(coverageMessage({...base, sections: [section('retrieved')]}), /could not be retrieved|not checked/);
});

test('downloads are a header button; the options stay hidden until it is opened', () => {
  const html = renderToStaticMarkup(React.createElement(PdfValidationDownloads, {result: report, file: {}}));
  assert.ok(html.includes('Download documents') && html.includes('aria-expanded="false"'));
  assert.ok(!html.includes('Download official PDF') && !html.includes('Download updated PDF'));
  assert.equal(renderToStaticMarkup(React.createElement(PdfValidationDownloads, {result: {...report, comparison: 'not_checked'}})), '');
  assert.equal(renderToStaticMarkup(React.createElement(PdfValidationDownloads, {result: {...report, source_sha256: null}})), '');
});
