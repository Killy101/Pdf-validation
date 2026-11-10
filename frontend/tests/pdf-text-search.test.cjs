const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {renderToStaticMarkup} = require('react-dom/server');
const React = require('react');

const {load} = require('./load-module.cjs');

const {PdfValidationPreview} = load('src/components/pdf-validation/PdfValidationPreview.tsx', {
  '@/lib/pdfValidation': {searchPdfText: async () => ({})},
  '@/lib/pdfFindingLocation': {findingOnPdfPage: () => false, findingPdfPages: () => []},
  './PdfHighlightedPage': {PdfHighlightedPage: () => null},
});

const render = props => renderToStaticMarkup(React.createElement(PdfValidationPreview, {
  preview: 'blob:preview', page: 1, filename: 'a.pdf', className: 'panel', totalPages: 3, ...props,
}));

test('the uploaded PDF preview has a labelled search box for the PDF text', () => {
  const html = render({file: {name: 'a.pdf'}});
  assert.ok(html.includes('role="search"') && html.includes('aria-label="Search text in this PDF"'));
  assert.ok(html.includes('placeholder="Search text in this PDF"'));
  assert.ok(/<button[^>]*type="submit"[^>]*disabled=""[^>]*>[\s\S]*?Search<\/span>/.test(html), 'Search is disabled until two characters are typed');
});

test('the search box is hidden when there is no uploaded file to search', () => {
  assert.ok(!render({file: null}).includes('role="search"'));
  assert.ok(!render({file: {name: 'a.pdf'}, preview: ''}).includes('role="search"'));
});

test('the view passes the uploaded file to the preview', () => {
  const view = fs.readFileSync('src/components/pdf-validation/PdfValidationView.tsx', 'utf8');
  assert.equal((view.match(/<PdfValidationPreview/g) || []).length, 2);
  assert.equal((view.match(/filename=\{file\?\.name\}\s+file=\{file\}/g) || []).length, 2);
});
