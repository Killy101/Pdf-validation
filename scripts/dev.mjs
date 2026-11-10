// Development runner: compiles the Electron shell, starts the Next.js dev server, opens the app,
// and stops the dev server when the app closes. Used by `npm run dev`.
import { spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const devUrl = "http://localhost:3000";
const isWindows = process.platform === "win32";

function fail(message) {
  console.error(message);
  process.exit(1);
}

const compiled = spawnSync(process.execPath, [require.resolve("typescript/bin/tsc"), "-p", "electron"], { cwd: root, stdio: "inherit" });
if (compiled.status !== 0) fail("The desktop shell failed to compile (see the messages above).");

const web = spawn("npm --prefix frontend run dev", { cwd: root, shell: true, stdio: "inherit" });
let finished = false;

function stopWeb() {
  if (!web.pid || web.exitCode !== null) return;
  if (isWindows) spawnSync("taskkill", ["/PID", String(web.pid), "/T", "/F"], { stdio: "ignore" });
  else web.kill("SIGTERM");
}

function finish(code) {
  if (finished) return;
  finished = true;
  stopWeb();
  process.exit(code);
}

let appStarted = false;
web.on("exit", (code) => {
  if (finished) return;
  if (appStarted) console.warn(`The interface server stopped (code ${code}). The open app keeps running, but hot reload is gone.`);
  else fail(`The interface server stopped unexpectedly (code ${code}).`);
});
process.on("SIGINT", () => finish(130));
process.on("SIGTERM", () => finish(143));

function answers() {
  return new Promise((resolve) => {
    const request = http.get(devUrl, (response) => { response.resume(); resolve(response.statusCode === 200); });
    request.on("error", () => resolve(false));
    request.setTimeout(3000, () => { request.destroy(); resolve(false); });
  });
}

const deadline = Date.now() + 120_000;
while (!(await answers())) {
  if (Date.now() > deadline) { stopWeb(); fail("The interface server did not start within 2 minutes."); }
  await new Promise((resolve) => setTimeout(resolve, 500));
}

appStarted = true;
const electron = spawn(require("electron"), ["."], {
  cwd: root, stdio: "inherit", env: { ...process.env, PDF_VALIDATION_DEV_URL: devUrl },
});
electron.on("error", (error) => { console.error(`Could not start Electron: ${error.message}`); finish(1); });
electron.on("exit", (code) => finish(code ?? 0));
