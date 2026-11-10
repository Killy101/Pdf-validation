"""Start the localhost API; the desktop shell passes the port and shared token."""
import argparse
import logging
import os
import platform
import sys
import threading
import time

import uvicorn

from app.logging_setup import APP, log_event, session_id, setup_logging

SHUTDOWN_GRACE_SECONDS = 5


def exit_when_stdin_closes(server: uvicorn.Server):
    # The shell keeps our stdin open, so end of input means the shell is gone.
    sys.stdin.buffer.read()
    log_event(APP, logging.INFO, "backend.shutdown_requested", reason="shell_closed_stdin")
    server.should_exit = True
    time.sleep(SHUTDOWN_GRACE_SECONDS)
    log_event(APP, logging.WARNING, "backend.forced_exit", reason="graceful_shutdown_timed_out")
    os._exit(0)


def main():
    # The packaged executable doubles as the isolated analysis worker (see worker_process.worker_command).
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        from app.services.worker_process import run_worker
        run_worker(sys.argv[2])
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--exit-on-stdin-close", action="store_true")
    args = parser.parse_args()
    setup_logging()
    log_event(APP, logging.INFO, "backend.starting", pid=os.getpid(), port=args.port, python=platform.python_version(),
              session_id=session_id(), exit_on_stdin_close=args.exit_on_stdin_close)
    try:
        from app.desktop_main import app
        config = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_config=None, log_level="info",
                                timeout_keep_alive=3600, timeout_graceful_shutdown=3)
        server = uvicorn.Server(config)
        if args.exit_on_stdin_close:
            threading.Thread(target=exit_when_stdin_closes, args=(server,), daemon=True).start()
        server.run()
    except SystemExit as exc:
        if exc.code not in (0, None):
            log_event(APP, logging.ERROR, "backend.exited", code=exc.code, reason="server_stopped_abnormally_such_as_port_unavailable")
        raise
    except Exception as exc:
        log_event(APP, logging.CRITICAL, "backend.crashed", exc_info=exc, error=type(exc).__name__)
        raise
    log_event(APP, logging.INFO, "backend.stopped", pid=os.getpid())


if __name__ == "__main__":
    main()
