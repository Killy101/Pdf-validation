const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

function load(filename) {
  const module = {exports: {}};
  const code = ts.transpileModule(fs.readFileSync(`src/lib/${filename}.ts`, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS},
  }).outputText;
  new Function('exports', 'module', code)(module.exports, module);
  return module.exports;
}

const {findingPdfPages, findingOnPdfPage, findingPageLabel} = load('pdfFindingLocation');
const {computeWordDiff} = load('pdfDiffUtils');

test('page ranges include every affected page and keep interior pages selectable', () => {
  const finding = {pdf_page: 3, pdf_page_end: 6, approximate_location: false};
  assert.deepEqual(findingPdfPages(finding), [3, 4, 5, 6]);
  assert.ok(findingOnPdfPage(finding, 5));
  assert.ok(!findingOnPdfPage(finding, 7));
  assert.equal(findingPageLabel(finding), 'Uploaded PDF pages 3-6');
});

test('older reports retain single pages and missing text remains an approximate location', () => {
  assert.deepEqual(findingPdfPages({pdf_page: 4}), [4]);
  assert.equal(findingPageLabel({pdf_page: 4, approximate_location: true}), 'Near uploaded PDF page 4');
  assert.equal(findingPageLabel({pdf_page: null}), 'Document-level finding');
  assert.deepEqual(findingPdfPages({pdf_page: null}), []);
  assert.deepEqual(findingPdfPages({pdf_page: 0}), []);
  assert.deepEqual(findingPdfPages({pdf_page: 3, pdf_page_end: 999999}, 5), [3, 4, 5]);
});

test('readable diffs preserve each original excerpt while highlighting meaningful wording', () => {
  const expected = 'The application requires 30 days.\nKeep a signed copy.';
  const actual = 'The application requires 60 days.\nKeep a signed copy.';
  const diff = computeWordDiff(expected, actual);
  assert.equal(diff.expectedParts.map(part => part.value).join(''), expected);
  assert.equal(diff.actualParts.map(part => part.value).join(''), actual);
  assert.equal(diff.actualParts.filter(part => part.type === 'added').map(part => part.value).join('').trim(), '60');
  assert.equal(diff.expectedParts.filter(part => part.type === 'removed').map(part => part.value).join('').trim(), '30');
  assert.equal(diff.changesCount, 2);
});

test('display formatting and capitalization alone do not become content differences', () => {
  const diff = computeWordDiff('Regulation\nThe rule applies.', 'REGULATION The rule applies.');
  assert.equal(diff.hasDifferences, false);
  assert.equal(diff.actualParts.map(part => part.value).join(''), 'REGULATION The rule applies.');
});
