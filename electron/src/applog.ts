// Appends shell events to logs/<date>/application.log in the same line format as the Python backend.
// Logging problems are ignored on purpose: they must never stop the application.
import { appendFileSync, mkdirSync } from "node:fs";
import path from "node:path";

export type Fields = Record<string, string | number | boolean | undefined | null>;

let root: string | null = null;
let session = "";

export function init(logRoot: string, sessionId: string): void {
  root = logRoot;
  session = sessionId;
}

export const ready = (): boolean => root !== null;
export const logRoot = (): string | null => root;
export const sessionId = (): string => session;

export function newSessionId(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

// Values with spaces or special characters are quoted so one event always stays on one line.
function quote(value: string): string {
  return /^[A-Za-z0-9_./:@%+-]+$/.test(value) ? value : JSON.stringify(value);
}

export function event(level: string, name: string, fields: Fields = {}): void {
  if (!root) return;
  try {
    const d = new Date();
    const p = (n: number, width = 2) => String(n).padStart(width, "0");
    const day = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    const time = `${day} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
    const details = Object.entries(fields)
      .filter(([, value]) => value !== undefined && value !== null)
      .map(([key, value]) => ` ${key}=${quote(String(value))}`)
      .join("");
    const line = `${time} | ${level.padEnd(8)} | app.shell | session=${session} req=- | event=${name}${details}\n`;
    const folder = path.join(root, day);
    mkdirSync(folder, { recursive: true });
    appendFileSync(path.join(folder, "application.log"), line, "utf8");
  } catch {
    // never interrupt the app because a log entry could not be written
  }
}

export const info = (name: string, fields?: Fields) => event("INFO", name, fields);
export const warning = (name: string, fields?: Fields) => event("WARNING", name, fields);
export const error = (name: string, fields?: Fields) => event("ERROR", name, fields);
