# PDF Validation Desktop

Desktop version of the Reflink Automation Hub PDF Validation module. Electron owns the window, Next.js renders the UI, and a Python sidecar does all scraping, retrieval and comparison.

```text
Electron window -> Next.js static UI -> HTTP on 127.0.0.1 + bearer token -> Python sidecar (FastAPI)
```

The Electron main process (`electron/src`, TypeScript) picks a free port, generates a random token, starts the sidecar, and gives both to the page through a small preload bridge (`window.pdfValidation.backendInfo()`). Closing the app (or a crash) ends the sidecar because the shell holds its stdin open.

The full technical guide (architecture, running, rebuilding the exe and installer, signing, configuration, logs, API, troubleshooting) is [docs/PDF-Validation-Technical-Guide.docx](docs/PDF-Validation-Technical-Guide.docx).

## Layout

| Path | Contents |
|---|---|
| `backend/app/services/pdf_validation*.py`, `backend/app/pdf_validation_models.py` | Copied unchanged from the hub |
| `backend/app/routers/pdf_validation.py` | Hub routes; only the auth import changed |
| `backend/app/{config,auth,api_responses,desktop_main}.py`, `backend/run_server.py` | Desktop-only: slim settings, local token auth, response envelope, server entry |
| `backend/app/{logging_setup,validation_log}.py`, `backend/app/routers/client_events.py` | Logging: dated files, redaction, validation events, UI action events |
| `run.bat`, `scripts/launch.ps1` | Double-click launcher (checks, setup, start, shutdown, logging) |
| `backend/reflink/url/` | The four URL helpers the module calls, copied verbatim |
| `frontend/` | Next.js static export; `components/pdf-validation` and the `pdf*` libs are the hub files, `lib/api.ts` is the new local client |
| `electron/src/` | Electron shell in TypeScript: window, `app://` interface server, sidecar start/stop, shell logging |
| `scripts/build-backend.ps1`, `scripts/sign.ps1`, `scripts/test-backend-exe.ps1` | Engine build (PyInstaller), code signing, standalone engine smoke test |
| `scripts/dev.mjs` | `npm run dev`: compiles the shell, starts the Next.js dev server, opens Electron |
| `tests/`, `frontend/tests/` | The hub's PDF validation tests |

Settings keep the hub's names, for example `PDF_VALIDATION_MAX_FILES` or `PDF_VALIDATION_ALLOWED_HOSTS`, and are read from the environment or `backend/.env`.

## Prerequisites

Node 18+ and Python 3.10+ (tested with 3.14). Nothing else to install and no admin rights needed: Electron is a normal npm package. Windows browser collection uses the installed Microsoft Edge. The launcher checks all of this and says what is missing.

## Start (Windows)

Double-click `run.bat`. It starts the **packaged** app (no Python or Node needed at run time):

1. finds `release\win-unpacked\PDF Validation.exe`, or the copy installed by the setup program (`%LOCALAPPDATA%\Programs\PDF Validation`); `-AppPath` picks another one;
2. checks the app, interface and validation engine files, and reports whether they are code-signed;
3. refuses to start a second copy and stops a leftover engine of this copy from an earlier crash;
4. starts the app, waits until the engine reports ready, and when the window closes confirms the engine shut down.

| Command | What it does |
|---|---|
| `run.bat` | Start the packaged app |
| `run.bat -Build` | Set up `.venv` and npm packages, run `npm run build`, then start the result |
| `run.bat -Dev` | Development mode from source (`npm run dev`, port 3000) |
| `run.bat -CheckOnly` | Report what is ready or missing without starting anything |

On any problem it prints what failed and what to do, keeps the logs, and waits for a key press so the window never closes on an error.

The Electron shell owns the single Python backend process (the launcher never starts a second one), so closing the window, or a crash of the shell, always ends the backend: the shell closes its stdin, the backend finishes its work and exits, and the shell kills it only if that takes more than 8 seconds.

## Logs

Everything is written under `logs/<YYYY-MM-DD>/` next to `run.bat` (a new folder starts at midnight, folders older than 30 days are removed):

| File | Contents |
|---|---|
| `application.log` | Launcher, desktop shell and backend lifecycle (start, ready, stop), user actions in the UI, and every error from any component with its full traceback |
| `validation.log` | Validation activity: each PDF processed, source retrieval and website scraping (URL, kind, bytes, attempts, time), discovery, batches, downloads, the result (`match`, `mismatch`, `needs_review`, `unable`) with the reasons and findings, missing or rejected files |
| `backend.log` | HTTP requests (method, path, status, time, request id) and server output |
| `shell.log` | Raw output of the tools the launcher ran (`npm`, `pip`) |

One line per event, the same format in every file:

```text
2026-11-10 11:06:06.070 | INFO     | validation.result | session=20261110-110604 req=7f2b30f0 | event=validation.result.mismatch file=regulation-b.pdf comparison=content findings=1 reason="..."
```

`session` is the launcher run and `req` ties together everything a single request logged. Files rotate at 5 MB (5 backups). Tokens, passwords and sensitive URL parameters are never written; URLs are logged without credentials, and PDF text is not logged. A logging failure never interrupts the app. Options (environment or `backend/.env`): `PDF_VALIDATION_LOG_DIR`, `PDF_VALIDATION_LOG_LEVEL` (set `DEBUG` for more detail), `PDF_VALIDATION_LOG_MAX_BYTES`, `PDF_VALIDATION_LOG_BACKUPS`, `PDF_VALIDATION_LOG_RETENTION_DAYS`. An installed build without the launcher logs to the app log directory instead.

## Develop

`run.bat` does the setup below automatically. Manually:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt pytest httpx
npm install
npm --prefix frontend install
npm run dev
```

`npm run dev` starts Next.js and the Electron window (`npm start` runs the production-style build served from `app://local`); the sidecar uses `.venv`. Set `PDF_VALIDATION_PYTHON` to use another interpreter.

For the UI in a plain browser, run the sidecar yourself (`PDF_VALIDATION_DESKTOP_TOKEN=dev backend/run_server.py --port 8765`) and start `frontend` with `NEXT_PUBLIC_PDF_API_TOKEN=dev`.

## Build the installer

```powershell
npm run build            # = npm run build:backend, then npm run build:app
```

- `build:backend` (`scripts/build-backend.ps1`) builds the validation engine with PyInstaller (`backend/pdf-validation-backend.spec`) into `electron/resources/backend/pdf-validation-backend.exe` (one folder, about 180 MB, includes the Playwright driver; browser pages use the installed Microsoft Edge). The same exe runs the isolated analysis workers (`--worker <module>`). It is then signed (if configured) and smoke-tested with a clean environment by `scripts/test-backend-exe.ps1`.
- `build:app` builds the Next.js static interface and the Electron shell, and electron-builder writes `release/win-unpacked/` and `release/PDF Validation Setup <version>.exe`. The Next.js interface is never packed into PyInstaller.

Test a built engine on its own (also against live sites):

```powershell
.\scripts\test-backend-exe.ps1 -SamplePdf C:\path\title4.pdf -Query "The Supreme" `
  -Url https://legislature.maine.gov/statutes/4/title4.pdf -ReferenceUrl https://legislature.maine.gov/statutes/
```

Packaged paths: the engine reads optional settings from `%LOCALAPPDATA%\PDF Validation\backend.env` (or `PDF_VALIDATION_ENV_FILE`), logs to the folder the shell passes (`%APPDATA%\PDF Validation\logs` when started from the Start menu, `logs\` when started by `run.bat`), and keeps temporary data in `%TEMP%`. Nothing is written next to the installed files.

## Code signing

Signing runs automatically during the build when a certificate is configured; otherwise the build prints `Not signed` and continues. Certificates and passwords are **never** stored in the repository (`*.pfx`, `*.p12`, `*.cer` are git-ignored); supply them through environment variables or the CI secret store:

| Variable | Meaning |
|---|---|
| `PDF_VALIDATION_SIGN_THUMBPRINT` | SHA-1 thumbprint of a code-signing certificate in the Windows certificate store (recommended; also works for USB tokens and cloud HSMs) |
| `PDF_VALIDATION_SIGN_PFX` + `PDF_VALIDATION_SIGN_PASSWORD` | A `.pfx` file outside the repository and its password |
| `PDF_VALIDATION_SIGN_TIMESTAMP` | Timestamp server (default `http://timestamp.digicert.com`) |
| `PDF_VALIDATION_SIGN_REQUIRED=1` | Fail the build instead of producing unsigned files (use for releases) |

`scripts/sign.ps1` uses `signtool` from the Windows SDK (SHA-256, RFC 3161 timestamp) and verifies every file with `Get-AuthenticodeSignature`. It signs the engine exe, and through `scripts/sign-hook.cjs` electron-builder sends `PDF Validation.exe`, the bundled `node.exe`, the installer and the uninstaller through the same script. Check a build:

```powershell
Get-AuthenticodeSignature "release\win-unpacked\PDF Validation.exe", "release\win-unpacked\resources\backend\pdf-validation-backend.exe" | Format-Table Status, SignerCertificate, Path
```

What you need: an OV or EV code-signing certificate from a public CA (DigiCert, Sectigo, GlobalSign, or Azure Trusted Signing). EV or established OV certificates avoid the SmartScreen "unknown publisher" warning.

## Tests

```powershell
npm run test:backend
npm run test:frontend
```
