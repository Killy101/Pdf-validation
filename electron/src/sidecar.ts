// Starts, watches and stops the Python backend. The shell keeps the child's stdin open so the
// backend exits on its own if this process dies; closing stdin is also the polite way to stop it.
import { ChildProcess, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";

import * as log from "./applog";

export interface BackendInfo { url: string; token: string }
export type BackendResult = { ok: true; info: BackendInfo } | { ok: false; error: string };

const STOP_GRACE_MS = 8000;
let child: ChildProcess | null = null;
let stopping = false;
let recentErrors = "";

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => (address && typeof address === "object" ? resolve(address.port) : reject(new Error("No free port."))));
    });
  });
}

// The packaged app runs the PyInstaller engine; development runs backend/run_server.py with the project's .venv.
export interface Locations { program: string; args: string[]; backend: string; missing: string }

export function locate(packaged: boolean, repoRoot: string, resources: string): Locations {
  if (packaged) {
    const backend = path.join(resources, "backend");
    return { program: path.join(backend, "pdf-validation-backend.exe"), args: [], backend,
      missing: "The validation engine is missing from this installation. Reinstall PDF Validation." };
  }
  const python = process.env.PDF_VALIDATION_PYTHON
    || path.join(repoRoot, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  return { program: python, args: ["run_server.py"], backend: path.join(repoRoot, "backend"),
    missing: "The Python runtime was not found. Run run.bat -Dev so the development environment can be set up." };
}

export async function start(where: Locations): Promise<BackendResult> {
  try {
    const port = await freePort();
    const token = randomBytes(32).toString("hex");
    log.info("backend.spawning", { program: where.program, backend_dir: where.backend, port });
    if (!existsSync(where.program)) {
      log.error("backend.spawn_failed", { reason: "program_not_found", program: where.program });
      return { ok: false, error: `${where.missing} (Not found: ${where.program})` };
    }
    const env: NodeJS.ProcessEnv = { ...process.env, PDF_VALIDATION_DESKTOP_TOKEN: token };
    const root = log.logRoot();
    if (root) {
      env.PDF_VALIDATION_LOG_DIR = root;
      env.PDF_VALIDATION_SESSION_ID = log.sessionId();
    }
    const process_ = spawn(where.program, [...where.args, "--port", String(port), "--exit-on-stdin-close"], {
      cwd: where.backend, env, stdio: ["pipe", "ignore", "pipe"], windowsHide: true,
    });
    await new Promise<void>((resolve, reject) => {
      process_.once("spawn", () => resolve());
      process_.once("error", reject);
    });
    child = process_;
    process_.stderr?.on("data", (chunk: Buffer) => { recentErrors = (recentErrors + chunk.toString()).slice(-2000); });
    process_.stdin?.on("error", () => undefined);
    process_.on("exit", (code, signal) => {
      if (stopping) return;
      log.error("backend.exited_unexpectedly", { pid: process_.pid, code, signal, stderr: recentErrors.trim() || undefined });
    });
    log.info("backend.spawned", { pid: process_.pid, port });
    return { ok: true, info: { url: `http://127.0.0.1:${port}`, token } };
  } catch (error) {
    const message = `Could not start the validation engine (${where.program}): ${(error as Error).message}`;
    log.error("backend.spawn_failed", { reason: message });
    return { ok: false, error: message };
  }
}

// Closing stdin asks the backend to finish its work and exit; it is killed only if that takes too long.
export async function stop(): Promise<void> {
  const running = child;
  child = null;
  if (!running || running.exitCode !== null || running.signalCode !== null) return;
  stopping = true;
  const pid = running.pid;
  log.info("backend.stopping", { pid });
  const exited = new Promise<string>((resolve) => running.once("exit", (code, signal) => resolve(`code ${code ?? signal}`)));
  running.stdin?.end();
  let status: string | null = null;
  const timer = new Promise<null>((resolve) => setTimeout(() => resolve(null), STOP_GRACE_MS));
  status = await Promise.race([exited, timer]);
  if (status === null) running.kill();
  log.event(status === null ? "WARNING" : "INFO", "backend.stopped", { pid, graceful: status !== null, status: status ?? "killed" });
}
