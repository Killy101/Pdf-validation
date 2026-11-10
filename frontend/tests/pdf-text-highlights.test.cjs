const {test} = require('node:test');
const assert = require('node:assert/strict');
const {load} = require('./load-module.cjs');

const {highlightRanges, highlightBoxes} = load('src/lib/pdfTextHighlights.ts');
const matches = ranges => new Set(ranges.map(range => range.match)).size;

test('every occurrence on the page is found, ignoring case', () => {
  const ranges = highlightRanges([{str: 'MRS Title 4. JUDICIARY'}, {str: 'Title 4. Judiciary'}], 'judiciary');
  assert.equal(matches(ranges), 2);
  assert.deepEqual(ranges[0], {item: 0, start: 13, end: 22, match: 0});
});

test('a phrase is found across text pieces and line breaks', () => {
  const pieces = [{str: 'by the Supreme'}, {str: ' Judicial', hasEOL: true}, {str: 'Court and the'}];
  const ranges = highlightRanges(pieces, 'Supreme   Judicial\nCourt');
  assert.equal(matches(ranges), 1);
  assert.deepEqual(ranges.map(range => [range.item, range.start, range.end]), [[0, 7, 14], [1, 0, 9], [2, 0, 5]]);
});

test('soft hyphens and repeated spaces do not stop a match', () => {
  assert.equal(matches(highlightRanges([{str: 'the Su\u00adpreme  Court'}], 'supreme court')), 1);
});

test('short or absent search text highlights nothing', () => {
  assert.deepEqual(highlightRanges([{str: 'Court'}], 'c'), []);
  assert.deepEqual(highlightRanges([{str: 'Court'}], 'tribunal'), []);
});

test('boxes cover the matched share of the piece in viewport pixels', () => {
  const measure = {font: '', measureText: text => ({width: text.length * 10})};
  const identity = (first, second) => [second[0], second[1], second[2], second[3], second[4], second[5]];
  const pieces = [{str: 'abcdefghij', transform: [12, 0, 0, 12, 100, 500], width: 200, fontName: 'f'}];
  const [box] = highlightBoxes(pieces, {f: {fontFamily: 'serif'}}, 'cdef', {transform: [1, 0, 0, 1, 0, 0], scale: 1}, identity, measure);
  assert.equal(box.left, 140);
  assert.equal(box.width, 80);
  assert.equal(box.top, 488);
});
