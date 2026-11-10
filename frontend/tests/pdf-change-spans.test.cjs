const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

const moduleUnderTest = {exports: {}};
const code = ts.transpileModule(fs.readFileSync('src/lib/pdfDiffUtils.ts', 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS},
}).outputText;
new Function('exports', 'module', code)(moduleUnderTest.exports, moduleUnderTest);
const {computeWordDiff} = moduleUnderTest.exports;

test('backend evidence highlights changed numbers while leaving excerpt context readable', () => {
  const result = computeWordDiff('Submit within 30 days.\nKeep records.', 'Submit within 60 days.\nKeep records.', [14, 16], [14, 16]);
  assert.deepEqual(result.expectedParts.filter(part => part.type === 'removed').map(part => part.value), ['30']);
  assert.deepEqual(result.actualParts.filter(part => part.type === 'added').map(part => part.value), ['60']);
  assert.equal(result.changesCount, 2);
  assert.equal(result.actualParts.map(part => part.value).join(''), 'Submit within 60 days.\nKeep records.');
});

test('insertion context around formula labels is not counted as changed wording', () => {
  const text = 'column 2 of that Part.\nPenalty range\nA\nB\nC\n25 (1) The range of penalties';
  const start = text.indexOf('A\nB\nC');
  const result = computeWordDiff('', text, [0, 0], [start, start + 5]);
  assert.equal(result.changesCount, 3);
  assert.equal(result.actualParts.find(part => part.type === 'added').value, 'A\nB\nC');
  assert.equal(result.unifiedParts.filter(part => part.type === 'same').map(part => part.value).join(''), text.slice(0, start) + text.slice(start + 5));
});

test('Unicode offsets use codepoints and legacy reports retain computed differences', () => {
  const result = computeWordDiff('Permit \u{1F4C4} 30 days', 'Permit \u{1F4C4} 60 days', [9, 11], [9, 11]);
  assert.equal(result.actualParts.find(part => part.type === 'added').value, '60');
  assert.ok(computeWordDiff('within 30 days', 'within 60 days').hasDifferences);
  assert.ok(computeWordDiff('within 30 days', 'within 60 days', [200, 201], [200, 201]).hasDifferences);
  assert.equal(computeWordDiff('Only deleted words.', '', [5, 12], [0, 0]).unifiedParts.find(part => part.type === 'removed').value, 'deleted');
});
