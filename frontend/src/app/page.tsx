"use client";

import { useEffect, useState } from "react";
import { Loader2, Moon, Sun, AlertTriangle, RefreshCw } from "lucide-react";
import { PdfValidationView } from "@/components/pdf-validation/PdfValidationView";
import { logClientEvent, waitForBackend } from "@/lib/api";
import { useTheme } from "@/context/ThemeContext";

type Engine = { state: "starting" } | { state: "ready" } | { state: "failed"; message: string };

export default function Home() {
  const [engine, setEngine] = useState<Engine>({ state: "starting" });
  const [attempt, setAttempt] = useState(0);
  const { theme, toggleTheme } = useTheme();

  useEffect(() => {
    const controller = new AbortController();
    setEngine({ state: "starting" });
    waitForBackend(controller.signal)
      .then(() => {
        if (controller.signal.aborted) return;
        setEngine({ state: "ready" });
        logClientEvent("engine_ready", { attempt }, "info", "app");
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setEngine({ state: "failed", message: error instanceof Error ? error.message : "The validation engine did not start." });
        }
      });
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    const onError = (event: ErrorEvent) => logClientEvent("window_error",
      { message: event.message, source: event.filename, line: event.lineno }, "error", "app");
    const onRejection = (event: PromiseRejectionEvent) => logClientEvent("unhandled_rejection",
      { message: event.reason instanceof Error ? event.reason.message : String(event.reason) }, "error", "app");
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  return (
    <main className="flex h-screen flex-col">
      <button type="button" onClick={toggleTheme} aria-label="Toggle dark mode"
        className="fixed right-3 top-3 z-40 rounded-xl border border-slate-200 bg-white p-2 text-slate-600 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700">
        {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>
      {engine.state === "ready" ? <PdfValidationView /> : (
        <div className="m-auto flex max-w-md flex-col items-center gap-3 p-6 text-center">
          {engine.state === "starting" ? (
            <>
              <Loader2 className="h-8 w-8 animate-spin text-sky-600" />
              <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">Starting the validation engine...</p>
            </>
          ) : (
            <>
              <AlertTriangle className="h-8 w-8 text-amber-600" />
              <p role="alert" className="text-sm font-semibold text-slate-700 dark:text-slate-200">The validation engine could not be reached.</p>
              <p className="text-xs text-slate-500">{engine.message}</p>
              <button type="button" onClick={() => setAttempt(value => value + 1)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
                <RefreshCw className="h-3.5 w-3.5" /> Try again
              </button>
            </>
          )}
        </div>
      )}
    </main>
  );
}
