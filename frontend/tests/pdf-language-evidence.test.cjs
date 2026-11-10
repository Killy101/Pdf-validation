const {test} = require('node:test');
const assert = require('node:assert/strict');
const {renderToStaticMarkup} = require('react-dom/server');
const React = require('react');

const {load} = require('./load-module.cjs');
const languages = load('src/lib/pdfLanguage.ts');
const {PdfValidationEvidence} = load('src/components/pdf-validation/PdfValidationEvidence.tsx', {'@/lib/pdfLanguage': languages});

test('language labels include non-English names without calling an unknown script a specific language', () => {
  assert.equal(languages.pdfLanguageName('fr'), 'French');
  assert.equal(languages.pdfLanguageName('es'), 'Spanish');
  assert.equal(languages.pdfLanguageName('ja'), 'Japanese');
  assert.equal(languages.pdfLanguageName('ko'), 'Korean');
  assert.match(languages.pdfLanguageName('und-Arab'), /script; language not determined/);
  assert.equal(languages.pdfLanguageName('unknown'), 'Language not determined');
  assert.equal(languages.pdfLanguageName('invalid_code'), 'invalid_code');
});

test('comparison evidence reports the selected source language and unresolved alignment', () => {
  const report = {pdf_layout: {columns: 1, languages: ['fr']}, source_layout: {columns: 2, languages: ['en', 'fr'], parallel_bilingual: true},
    comparison_language: 'fr', language_alignment: 'selected'};
  const html = renderToStaticMarkup(React.createElement(PdfValidationEvidence, {result: report}));
  assert.ok(html.includes('French only') && html.includes('Single main text column; French'));
  const review = renderToStaticMarkup(React.createElement(PdfValidationEvidence, {result: {...report, language_alignment: 'needs_review'}}));
  assert.ok(review.includes('Language selection needs review') && !review.includes('French only'));
});
