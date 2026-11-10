// Desktop shell: owns the window, serves the static interface, and runs the single Python backend.
import { app, BrowserWindow, dialog, ipcMain, Menu, net, protocol, shell } from "electron";
import { existsSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import * as log from "./applog";
import * as sidecar from "./sidecar";

const repoRoot = path.resolve(__dirname, "..", "..");
const devUrl = process.env.PDF_VALIDATION_DEV_URL;
const interfaceRoot = app.isPackaged ? path.join(process.resourcesPath, "frontend") : path.join(repoRoot, "frontend", "out");
const APP_ORIGIN = "app://local";

let backend: Promise<sidecar.BackendResult> | null = null;
let window: BrowserWindow | null = null;
let quitting = false;

protocol.registerSchemesAsPrivileged([{ scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: true } }]);

// The launcher passes its log folder and session; a normal install logs to the app log directory.
function startLogging(): void {
  const root = process.env.PDF_VALIDATION_LOG_DIR || (app.isPackaged ? app.getPath("logs") : path.join(repoRoot, "logs"));
  log.init(root, process.env.PDF_VALIDATION_SESSION_ID || log.newSessionId());
}

function serveInterface(): void {
  protocol.handle("app", (request) => {
    const requested = decodeURIComponent(new URL(request.url).pathname);
    const file = path.normalize(path.join(interfaceRoot, requested.endsWith("/") ? requested + "index.html" : requested));
    if (!file.startsWith(interfaceRoot) || !existsSync(file)) return new Response("Not found", { status: 404 });
    return net.fetch(pathToFileURL(file).toString());
  });
}

function createWindow(): void {
  window = new BrowserWindow({
    width: 1280, height: 820, minWidth: 1024, minHeight: 640, title: "PDF Validation", show: false,
    icon: path.join(repoRoot, "electron", "assets", "icon.ico"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  const contents = window.webContents;
  window.once("ready-to-show", () => { window?.show(); log.info("app.window_shown"); });
  window.on("closed", () => { window = null; });
  // Links to websites open in the normal browser; the app window itself never navigates away.
  contents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    if (!url.startsWith(APP_ORIGIN) && !(devUrl && url.startsWith(devUrl))) event.preventDefault();
  });
  contents.on("did-fail-load", (_event, code, description, url, isMainFrame) => {
    if (!isMainFrame) return;
    log.error("app.load_failed", { code, description, url });
    dialog.showErrorBox("PDF Validation", `The interface could not be loaded (${description}). Details are in the logs folder.`);
  });
  contents.on("render-process-gone", (_event, details) => log.error("app.renderer_gone", { reason: details.reason, exit_code: details.exitCode }));
  void window.loadURL(devUrl || `${APP_ORIGIN}/index.html`);
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.focus();
  });

  process.on("uncaughtException", (error) => log.error("shell.uncaught_exception", { error: error.name, message: error.message, stack: error.stack }));
  process.on("unhandledRejection", (reason) => log.error("shell.unhandled_rejection", { reason: String(reason) }));

  app.whenReady().then(() => {
    startLogging();
    log.info("app.starting", { version: app.getVersion(), electron: process.versions.electron, packaged: app.isPackaged, mode: devUrl ? "dev" : "static" });
    if (app.isPackaged) Menu.setApplicationMenu(null);
    serveInterface();
    backend = sidecar.start(sidecar.locate(app.isPackaged, repoRoot, process.resourcesPath));
    ipcMain.handle("backend-info", () => backend);
    createWindow();
  });

  app.on("window-all-closed", () => app.quit());

  // Stop the backend before the process ends so shutdown is graceful and logged.
  app.on("before-quit", (event) => {
    if (quitting) return;
    quitting = true;
    event.preventDefault();
    log.info("app.exit_requested");
    sidecar.stop().finally(() => {
      log.info("app.exited");
      app.exit(0);
    });
  });
}
