const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

function load(download = async () => new Blob(['%PDF-synthetic'])) {
  const module = {exports: {}};
  const code = ts.transpileModule(fs.readFileSync('src/lib/pdfValidationDownloads.ts', 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS},
  }).outputText;
  new Function('require', 'exports', 'module', code)(() => ({apiDownload: download}), module.exports, module);
  return module.exports;
}

const report = {filename: 'uploaded.pdf', source_url: 'https://publisher.example/edition.pdf', source_type: 'pdf',
  source_sha256: 'b'.repeat(64), comparison: 'content', coverage_complete: true, document_identity: 'match'};

test('official download uses the selected source URL and digest, including historical versions', async () => {
  const calls = [];
  const {fetchValidationPdf} = load(async (...args) => {calls.push(args); return new Blob(['%PDF-official']);});
  const result = {...report, source_url: 'https://publisher.example/old-edition.pdf?year=2025'};
  const signal = new AbortController().signal;
  assert.equal(await (await fetchValidationPdf(result, 'official', undefined, signal)).text(), '%PDF-official');
  const [endpoint, sentSignal] = calls[0];
  const params = new URL(endpoint, 'https://app.example').searchParams;
  assert.equal(params.get('source_url'), result.source_url);
  assert.equal(params.get('source_sha256'), result.source_sha256);
  assert.equal(sentSignal, signal);
});

test('updated download sends the upload and selected source as multipart data', async () => {
  let request;
  const {fetchValidationPdf} = load(async (...args) => {request = args; return new Blob(['%PDF-updated']);});
  const file = new Blob(['%PDF-upload']);
  await fetchValidationPdf(report, 'updated', file);
  assert.equal(request[0], '/pdf-validations/updated-pdf');
  assert.equal(request[2].method, 'POST');
  assert.equal(await request[2].body.get('document').text(), '%PDF-upload');
  assert.equal(request[2].body.get('source_url'), report.source_url);
  assert.equal(request[2].body.get('source_sha256'), report.source_sha256);
});

test('generation is disabled for unconfirmed identity, incomplete coverage, and missing uploads', async () => {
  const {pdfDownloadAvailability, fetchValidationPdf} = load(() => {throw new Error('Unexpected request');});
  for (const changes of [{document_identity: 'needs_review'}, {document_identity: 'mismatch'}, {coverage_complete: false}]) {
    const result = {...report, ...changes};
    assert.equal(pdfDownloadAvailability(result, true).updated, false);
    assert.equal(pdfDownloadAvailability(result, true).official, true);
    await assert.rejects(fetchValidationPdf(result, 'updated', new Blob()), /unavailable/);
  }
  assert.equal(pdfDownloadAvailability(report, false).updated, false);
  assert.deepEqual(pdfDownloadAvailability({...report, comparison: 'not_checked'}, true), {official: false, updated: false});
  assert.equal(pdfDownloadAvailability({...report, source_type: 'html'}, true).official, false);
});

test('unexpected HTML is rejected and backend source-change errors remain actionable', async () => {
  await assert.rejects(load(async () => new Blob(['<html>Error</html>'])).fetchValidationPdf(report, 'official'), /did not return a PDF/);
  await assert.rejects(load(async () => {throw new Error('The source has changed. Validate again.');}).fetchValidationPdf(report, 'official'), /Validate again/);
});

test('download filenames distinguish official files and rebuilt uploads', () => {
  const {pdfDownloadFilename} = load();
  assert.equal(pdfDownloadFilename(report, 'official'), 'edition.pdf');
  assert.equal(pdfDownloadFilename(report, 'updated'), 'uploaded-updated.pdf');
  assert.equal(pdfDownloadFilename({...report, source_url: 'https://publisher.example/'}, 'official'), 'source-document.pdf');
  assert.doesNotMatch(pdfDownloadFilename({...report, filename: '../unsafe:name.pdf'}, 'updated'), /[/\\:]/);
});

test('ZIP downloads transmit archive and member provenance and use the member filename', async () => {
  const calls = [];
  const api = load(async (...args) => { calls.push(args); return new Blob(['%PDF-source']); });
  const result = {...report, source_url: 'https://publisher.example/book.zip', archive_source: {
    member: 'editions/current.pdf', sha256: 'c'.repeat(64), member_sha256: report.source_sha256
  }};
  await api.fetchValidationPdf(result, 'official');
  const params = new URL(calls[0][0], 'https://app.example').searchParams;
  assert.equal(params.get('source_url'), result.source_url);
  assert.equal(params.get('source_sha256'), result.source_sha256);
  assert.equal(params.get('archive_member'), 'editions/current.pdf');
  assert.equal(params.get('archive_sha256'), result.archive_source.sha256);
  assert.equal(api.pdfDownloadFilename(result, 'official'), 'current.pdf');
  await api.fetchValidationPdf(result, 'updated', new Blob(['%PDF-upload']));
  assert.equal(calls[1][2].body.get('archive_member'), result.archive_source.member);
  assert.equal(calls[1][2].body.get('archive_sha256'), result.archive_source.sha256);
});
