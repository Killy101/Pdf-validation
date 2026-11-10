const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {File} = require('node:buffer');
const ts = require('typescript');

function load(response) {
  const calls = [], module = {exports: {}};
  const code = ts.transpileModule(fs.readFileSync('src/lib/pdfValidation.ts', 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS},
  }).outputText;
  new Function('require', 'exports', 'module', code)(() => ({ApiError: class extends Error {}, apiRequest: (url, options) => {
    calls.push({url, ...options});
    const workflow = options.body instanceof FormData ? options.body.get('workflow') : options.body ? JSON.parse(options.body).workflow : undefined;
    return Promise.resolve(response ?? {workflow});
  }}), module.exports, module);
  return {...module.exports, calls};
}

const range = {workflow: 'date_range', date_start: '2025-09-01', date_end: '2025-09-30'};

test('historical discovery and validation transmit dates and leave jurisdiction detection to the backend', async () => {
  const {discoverPdfSource, validatePdf, calls} = load();
  const signal = new AbortController().signal;
  await discoverPdfSource(' https://publisher.example/document ', signal, range);
  assert.deepEqual(JSON.parse(calls[0].body), {content_uri: 'https://publisher.example/document', ...range});
  await validatePdf(new File(['%PDF-synthetic'], 'synthetic.pdf'), 'https://publisher.example/document', undefined, signal, range);
  for (const [field, value] of Object.entries(range)) assert.equal(calls[1].body.get(field), value);
  assert.equal(calls[1].body.get('document').name, 'synthetic.pdf');
  assert.equal(calls[1].body.get('reference_url'), null);
  assert.equal(calls[1].body.get('jurisdiction'), null);
  assert.equal(calls[1].signal, signal);
});

test('switching to the current workflow omits hidden historical inputs', async () => {
  const {validatePdf, calls} = load();
  await validatePdf(new File(['%PDF-synthetic'], 'synthetic.pdf'), 'https://publisher.example/document', undefined,
    undefined, {...range, workflow: 'current', history_url: 'https://publisher.example/versions'});
  assert.equal(calls[0].body.get('workflow'), 'current');
  assert.equal(calls[0].body.get('jurisdiction'), null);
  assert.equal(calls[0].body.get('date_start'), null);
  assert.equal(calls[0].body.get('date_end'), null);
  assert.equal(calls[0].body.get('history_url'), null);
});

test('invalid date ranges fail before requests and a same-day range is supported', () => {
  const {checkPdfScope, discoverPdfSource, calls} = load();
  assert.throws(() => discoverPdfSource('https://publisher.example/document', undefined, {...range, date_end: ''}), /both/);
  assert.throws(() => checkPdfScope({...range, date_start: '2025-10-01'}), /on or before/);
  assert.throws(() => checkPdfScope({...range, date_start: '2025-02-30'}), /valid comparison/);
  assert.doesNotThrow(() => checkPdfScope({...range, date_end: range.date_start}));
  assert.equal(calls.length, 0);
});

test('a separate history page is included only in the historical request', async () => {
  const {discoverPdfSource, calls} = load();
  await discoverPdfSource('https://publisher.example/document', undefined,
    {...range, history_url: ' https://publisher.example/versions '});
  assert.equal(JSON.parse(calls[0].body).history_url, 'https://publisher.example/versions');
});

test('an older backend cannot silently return a current comparison for a historical request', async () => {
  const {discoverPdfSource, validatePdf} = load({workflow: 'current'});
  await assert.rejects(discoverPdfSource('https://publisher.example/document', undefined, range), /Restart the backend/);
  await assert.rejects(validatePdf(new File(['%PDF-synthetic'], 'synthetic.pdf'), 'https://publisher.example/document',
    undefined, undefined, range), /Restart the backend/);
});

test('batch creation binds scope and reference and every upload transmits its batch identifier', async () => {
  const batchId = 'b'.repeat(32);
  const {createPdfValidationBatch, releasePdfValidationBatch, validatePdf, calls} = load({batch_id: batchId});
  const signal = new AbortController().signal, reference = 'https://publisher.example/current.pdf';
  assert.equal(await createPdfValidationBatch(' https://publisher.example/document ', reference, signal), batchId);
  assert.deepEqual(JSON.parse(calls[0].body), {content_uri: 'https://publisher.example/document', reference_url: reference, workflow: 'current'});
  await validatePdf(new File(['%PDF-synthetic'], 'synthetic.pdf'), 'https://publisher.example/document', reference, signal, {}, batchId);
  assert.equal(calls[1].body.get('batch_id'), batchId);
  await releasePdfValidationBatch(batchId);
  assert.equal(calls[2].url, '/pdf-validations/batches/' + batchId);
  assert.equal(calls[2].method, 'DELETE');
  assert.equal(calls[2].signal, undefined);
});

test('a missing batch contract requires a backend restart before uploading PDFs', async () => {
  const {createPdfValidationBatch, calls} = load({});
  await assert.rejects(createPdfValidationBatch('https://publisher.example/document'), /Restart the backend/);
  assert.equal(calls.length, 1);
});

test('archive selections have unique keys and bind the same member to batches and uploads', async () => {
  const api = load({batch_id: 'a'.repeat(32)});
  const url = 'https://publisher.example/book.zip', options = {archive_member: 'editions/one.pdf'};
  const first = {url, archive_member: options.archive_member}, second = {url, archive_member: 'editions/two.pdf'};
  assert.notEqual(api.pdfReferenceKey(first), api.pdfReferenceKey(second));
  assert.equal(api.pdfReferenceKey({url}), url);
  await api.createPdfValidationBatch(url, url, undefined, options);
  await api.validatePdf(new File(['%PDF-upload'], 'upload.pdf'), url, url, undefined, options, 'a'.repeat(32));
  assert.equal(JSON.parse(api.calls[0].body).archive_member, options.archive_member);
  assert.equal(api.calls[1].body.get('archive_member'), options.archive_member);
  assert.equal(api.calls[1].body.get('reference_url'), url);
});
