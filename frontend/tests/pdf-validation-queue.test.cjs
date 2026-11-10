const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

function load(validatePdf, batch = {}) {
  const module = {exports: {}};
  const code = ts.transpileModule(fs.readFileSync('src/lib/pdfValidationQueue.ts', 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS},
  }).outputText;
  new Function('require', 'exports', 'module', code)(name => name === './api' ? {ApiError} : {validatePdf,
    createPdfValidationBatch: batch.create ?? (async () => 'a'.repeat(32)),
    releasePdfValidationBatch: batch.release ?? (async () => {})}, module.exports, module);
  return module.exports;
}

const configuration = {max_files: 10, max_upload_bytes: 4096, max_pages: 2000, timeout_seconds: 180};
const files = count => Array.from({length: count}, (_, index) => ({name: `synthetic-${index + 1}.pdf`, size: 1024}));
const report = filename => ({filename, comparison: 'content', references: [], status: 'match'});
const tick = () => new Promise(resolve => setImmediate(resolve));

test('ten PDFs reach the backend one at a time in selection order with the same URL and reference', async () => {
  const calls = [], updates = [], gates = [];
  let active = 0, peak = 0;
  const {validatePdfQueue} = load(async (file, uri, reference, signal) => {
    peak = Math.max(peak, ++active);
    calls.push({filename: file.name, uri, reference, signal});
    await new Promise(resolve => gates.push(resolve));
    active--;
    return report(file.name);
  });
  const controller = new AbortController();
  const queue = validatePdfQueue(files(10), 'https://publisher.example/document', 'https://publisher.example/current.pdf',
    configuration, controller.signal, (index, item) => updates.push({index, ...item}));
  await tick();
  for (let index = 0; index < 10; index++) {
    assert.equal(calls.length, index + 1);
    assert.equal(calls[index].filename, `synthetic-${index + 1}.pdf`);
    assert.equal(calls[index].uri, 'https://publisher.example/document');
    assert.equal(calls[index].reference, 'https://publisher.example/current.pdf');
    assert.equal(calls[index].signal, controller.signal);
    gates[index]();
    await tick();
  }
  assert.equal(await queue, 'complete');
  assert.equal(peak, 1);
  assert.deepEqual(updates.filter(item => item.state === 'done').map(item => item.result.filename), files(10).map(file => file.name));
});

test('selection limits, file types, and individual upload sizes are checked before any request', async () => {
  let calls = 0;
  const {checkPdfFiles, validatePdfQueue} = load(async () => { calls++; });
  assert.throws(() => checkPdfFiles([], configuration), /between 1 and 10/);
  assert.throws(() => checkPdfFiles(files(11), configuration), /between 1 and 10/);
  assert.throws(() => checkPdfFiles(files(4), {...configuration, max_files: 3}), /between 1 and 3/);
  assert.throws(() => checkPdfFiles([{name: 'invalid.txt', size: 10}], configuration), /Choose a PDF/);
  assert.throws(() => checkPdfFiles([{name: 'large.pdf', size: 4097}], configuration), /upload limit/);
  assert.doesNotThrow(() => checkPdfFiles(files(10), configuration));
  await assert.rejects(validatePdfQueue(files(11), 'https://publisher.example/document', undefined,
    configuration, new AbortController().signal, () => {}), /between 1 and 10/);
  assert.equal(calls, 0);
});

test('one invalid file does not discard other results or stop later files', async () => {
  const updates = [], calls = [];
  const {validatePdfQueue} = load(async file => {
    calls.push(file.name);
    if (file.name === 'synthetic-2.pdf') throw new Error('Synthetic unreadable PDF.');
    return report(file.name);
  });
  assert.equal(await validatePdfQueue(files(3), 'https://publisher.example/document', undefined,
    configuration, new AbortController().signal, (index, item) => updates.push({index, ...item})), 'complete');
  assert.deepEqual(calls, files(3).map(file => file.name));
  assert.equal(updates.find(item => item.index === 1 && item.state === 'error').error, 'Synthetic unreadable PDF.');
  assert.equal(updates.filter(item => item.state === 'done').length, 2);
});

test('cancelling the second file keeps the first result and never starts the third file', async () => {
  const calls = [], updates = [];
  let release;
  const {validatePdfQueue} = load(async file => {
    calls.push(file.name);
    if (calls.length === 2) await new Promise(resolve => release = resolve);
    return report(file.name);
  });
  const controller = new AbortController();
  const queue = validatePdfQueue(files(3), 'https://publisher.example/document', undefined,
    configuration, controller.signal, (index, item) => updates.push({index, ...item}));
  await tick();
  controller.abort();
  release();
  assert.equal(await queue, 'cancelled');
  assert.equal(calls.length, 2);
  assert.deepEqual(updates.filter(item => item.state === 'done').map(item => item.index), [0]);
});

test('a reference selection request pauses the remaining PDFs', async () => {
  let calls = 0;
  const {validatePdfQueue} = load(async file => {
    calls++;
    return {...report(file.name), comparison: 'not_checked', references: [{url: 'https://publisher.example/edition.pdf'}]};
  });
  assert.equal(await validatePdfQueue(files(10), 'https://publisher.example/document', undefined,
    configuration, new AbortController().signal, () => {}), 'reference_required');
  assert.equal(calls, 1);
});

test('a CAPTCHA or inaccessible shared website pauses the queue and keeps its warning result', async () => {
  const updates = [];
  let calls = 0;
  const {validatePdfQueue} = load(async file => {
    calls++;
    return {...report(file.name), status: 'unable', comparison: 'not_checked', source_access_issue: 'captcha'};
  });
  assert.equal(await validatePdfQueue(files(10), 'https://publisher.example/document', undefined,
    configuration, new AbortController().signal, (index, item) => updates.push({index, ...item})), 'source_unavailable');
  assert.equal(calls, 1);
  assert.equal(updates.find(item => item.state === 'done').result.source_access_issue, 'captcha');
});

test('server availability and authentication errors pause the remaining queue', async () => {
  for (const status of [401, 403, 409, 429, 503]) {
    let calls = 0;
    const {validatePdfQueue} = load(async () => { calls++; throw new ApiError('Synthetic request failure.', status); });
    assert.equal(await validatePdfQueue(files(10), 'https://publisher.example/document', undefined,
      configuration, new AbortController().signal, () => {}), 'stopped');
    assert.equal(calls, 1);
  }
});

test('all queued PDFs retain the selected workflow and date range', async () => {
  const options = {workflow: 'date_range', date_start: '2025-09-01', date_end: '2025-09-30'};
  const scopes = [], updates = [];
  const {validatePdfQueue} = load(async (file, uri, reference, signal, scope) => {
    scopes.push(scope);
    return {...report(file.name), ...scope, versions: [{reference: {label: 'September edition'}, result: report(file.name)}]};
  });
  assert.equal(await validatePdfQueue(files(3), 'https://publisher.example/document', undefined,
    configuration, new AbortController().signal, (index, item) => updates.push(item), options), 'complete');
  assert.deepEqual(scopes, [options, options, options]);
  assert.equal(updates.filter(item => item.state === 'done')[0].result.versions[0].reference.label, 'September edition');
});

test('unavailable shared history stops later files and retains the explanatory result', async () => {
  let calls = 0;
  const updates = [];
  const {validatePdfQueue} = load(async file => {
    calls++;
    return {...report(file.name), workflow: 'date_range', versions: [], comparison: 'not_checked', status: 'needs_review'};
  });
  assert.equal(await validatePdfQueue(files(3), 'https://publisher.example/document', undefined,
    configuration, new AbortController().signal, (index, item) => updates.push(item)), 'history_unavailable');
  assert.equal(calls, 1);
  assert.equal(updates.find(item => item.state === 'done').result.status, 'needs_review');
});

test('one batch is created for the entire queue and released after successful or cancelled work', async () => {
  for (const cancel of [false, true]) {
    const events = [], controller = new AbortController(), options = {workflow: 'current'};
    const {validatePdfQueue} = load(async (file, uri, reference, signal, scope, batchId) => {
      events.push(['validate', batchId]);
      if (cancel) controller.abort();
      return report(file.name);
    }, {
      create: async (uri, reference, signal, scope) => {
        assert.equal(scope, options);
        events.push(['create', uri, reference]);
        return 'b'.repeat(32);
      },
      release: async batchId => events.push(['release', batchId]),
    });
    assert.equal(await validatePdfQueue(files(3), 'https://publisher.example/document', undefined,
      configuration, controller.signal, () => {}, options), cancel ? 'cancelled' : 'complete');
    assert.equal(events.filter(item => item[0] === 'create').length, 1);
    assert.equal(events.filter(item => item[0] === 'validate').length, cancel ? 1 : 3);
    assert.ok(events.slice(1).every(item => item[1] === 'b'.repeat(32)));
    assert.deepEqual(events.at(-1), ['release', 'b'.repeat(32)]);
  }
});

test('an aborted queue cannot create a batch and batch creation failure cannot start uploads', async () => {
  let creates = 0, uploads = 0;
  const {validatePdfQueue} = load(async () => { uploads++; }, {create: async () => {
    creates++;
    throw new ApiError('No batch slots available.', 503);
  }});
  const controller = new AbortController();
  controller.abort();
  assert.equal(await validatePdfQueue(files(3), 'https://publisher.example/document', undefined,
    configuration, controller.signal, () => {}), 'cancelled');
  assert.equal(creates, 0);
  await assert.rejects(validatePdfQueue(files(3), 'https://publisher.example/document', undefined,
    configuration, new AbortController().signal, () => {}), /No batch slots/);
  assert.equal(uploads, 0);
});

test('batch cleanup runs when a shared source stops the queue and cleanup failure preserves results', async () => {
  let releases = 0, updates = [];
  const {validatePdfQueue} = load(async file => ({...report(file.name), source_access_issue: 'rate_limited'}), {
    release: async () => { releases++; throw new Error('Synthetic cleanup failure.'); },
  });
  assert.equal(await validatePdfQueue(files(3), 'https://publisher.example/document', undefined,
    configuration, new AbortController().signal, (index, item) => updates.push(item)), 'source_unavailable');
  assert.equal(releases, 1);
  assert.equal(updates.filter(item => item.state === 'done').length, 1);
});

test('an ambiguous ZIP member pauses the queue even when its archive URL was selected', async () => {
  let uploads = 0, releases = 0;
  const url = 'https://publisher.example/book.zip';
  const {validatePdfQueue} = load(async file => {
    uploads++;
    return {...report(file.name), comparison: 'not_checked', references: [
      {url, archive_member: 'one.pdf'}, {url, archive_member: 'two.pdf'}
    ]};
  }, {release: async () => { releases++; }});
  assert.equal(await validatePdfQueue(files(3), url, url, configuration,
    new AbortController().signal, () => {}), 'reference_required');
  assert.equal(uploads, 1);
  assert.equal(releases, 1);
});
