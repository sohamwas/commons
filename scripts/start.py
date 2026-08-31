"""Bring the whole of Commons up with one command, without Docker.

    python scripts/start.py

From a clean clone that is everything: it creates the virtualenv, installs both sets of
dependencies, starts the gateway, the dashboard and the reference messaging vendor, waits
until each is actually answering, and prints where to look. Ctrl+C stops all of them.

WHY THIS EXISTS ALONGSIDE docker compose. Docker needs a working WSL2 backend on Windows,
which is a reboot and a 1GB install before you can see anything. This needs Python, which
the gateway already requires, and Node, which the dashboard already requires. Nothing else.
Both routes bring up the same three services on the same three ports.

It is deliberately stdlib only. A launcher whose job is to install the dependencies cannot
have dependencies.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
DASHBOARD = ROOT / "dashboard"

WINDOWS = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")

GATEWAY_PORT = 8787
DASHBOARD_PORT = 3300
MESSAGING_PORT = 8788

# Prefixes rather than colours: this output gets pasted into issues and chat windows,
# where escape codes turn into noise.
PREFIX = {"gateway": "[gateway  ]", "dashboard": "[dashboard]", "messaging": "[messaging]"}


def say(message: str) -> None:
    print(f"[commons  ] {message}", flush=True)


def die(message: str, *hints: str) -> None:
    print(f"\n  {message}\n", file=sys.stderr)
    for hint in hints:
        print(f"  {hint}", file=sys.stderr)
    print(file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- preflight


def port_in_use(port: int) -> bool:
    """Connect, do not bind.

    A bind test is unreliable here: on Windows binding 127.0.0.1 can succeed while another
    process holds 0.0.0.0 on the same port, so the check passes and the service then fails
    to start for reasons the check said were impossible.
    """
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def preflight(ports: list[int]) -> str:
    """`ports` must be the ports actually about to be used, not the defaults.

    Checking the module constants here instead meant --gateway-port was ignored by the
    very check whose error message recommends it: the run died complaining that 8787 was
    busy while it was about to bind 8801.
    """
    if sys.version_info < (3, 11):
        die(
            f"Python 3.11 or newer is required; this is {sys.version.split()[0]}.",
            "Install a newer Python and run this again.",
        )

    npm = shutil.which("npm")
    if not npm:
        die(
            "npm was not found on PATH, and the dashboard is a Next.js app.",
            "Install Node.js 20 or newer from https://nodejs.org and reopen your terminal.",
        )

    busy = [p for p in ports if port_in_use(p)]
    if busy:
        die(
            f"Something is already listening on {', '.join(str(p) for p in busy)}.",
            "Commons is probably already running. Stop it first, or pass --gateway-port /",
            "--dashboard-port to use different ports.",
        )
    return npm


# ---------------------------------------------------------------- setup


def run_step(label: str, command: list[str], cwd: Path) -> None:
    """A setup step whose output only matters when it fails."""
    say(label)
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        die(f"{label} failed.")


def ensure_python_env() -> None:
    if not VENV_PY.exists():
        run_step("creating .venv", [sys.executable, "-m", "venv", str(VENV)], ROOT)

    # Import rather than pip list: this asks the question that actually matters, which is
    # whether the gateway can start, not whether a package name appears in a manifest.
    probe = subprocess.run(
        [str(VENV_PY), "-c", "import commons.proxy.app"], cwd=str(ROOT), capture_output=True
    )
    if probe.returncode != 0:
        run_step("installing Python dependencies", [str(VENV_PY), "-m", "pip", "install", "-q", "-e", "."], ROOT)


def ensure_node_env(npm: str) -> None:
    if (DASHBOARD / "node_modules").is_dir():
        return
    # Several minutes on a cold cache, and silence for that long reads as a hang.
    say("installing dashboard dependencies (first run only, this takes a few minutes)")
    result = subprocess.run([npm, "ci"], cwd=str(DASHBOARD), capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        die("npm ci failed.")


def ensure_env_file() -> None:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if env.exists() or not example.exists():
        return
    shutil.copyfile(example, env)
    say(".env created from .env.example - add Razorpay test keys when you have them")


# ---------------------------------------------------------------- processes


def spawn(name: str, command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    # start_new_session puts the child in its own process group on POSIX, which is what
    # makes killpg in stop() able to reach the grandchildren. Without it there is no
    # group to signal and only the direct child dies.
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=not WINDOWS,
    )

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(f"{PREFIX[name]} {line.rstrip()}", flush=True)

    threading.Thread(target=pump, daemon=True).start()
    return proc


def stop(proc: subprocess.Popen) -> None:
    """Kill the whole tree.

    npm spawns next, which spawns its own server, so terminating the process we launched
    leaves the actual listener running and the port held. /T on Windows and killpg
    elsewhere are what make Ctrl+C actually free the ports.

    This used to call plain terminate() on POSIX, which contradicted the sentence above:
    it signals one process, not the group, so on macOS and Linux the dashboard survived
    Ctrl+C still holding 3300 and the next run died in preflight.
    """
    if proc.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if WINDOWS:
            proc.kill()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()


def wait_for(url: str, label: str, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return True
        except (urllib.error.URLError, OSError, ConnectionError):
            time.sleep(1.5)
    say(f"{label} did not answer within {timeout}s; leaving it running so you can read the log")
    return False


# ---------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description="Start Commons: gateway, dashboard, messaging vendor.")
    parser.add_argument("--mode", choices=["OBSERVE", "ENFORCE"], default="OBSERVE",
                        help="OBSERVE records decisions and blocks nothing (default)")
    parser.add_argument("--db", default="commons.db")
    parser.add_argument("--gateway-port", type=int, default=GATEWAY_PORT)
    parser.add_argument("--dashboard-port", type=int, default=DASHBOARD_PORT)
    parser.add_argument("--no-messaging", action="store_true",
                        help="skip the local reference vendor")
    args = parser.parse_args()

    want_messaging = not args.no_messaging
    ports = [args.gateway_port, args.dashboard_port]
    if want_messaging:
        ports.append(MESSAGING_PORT)
    npm = preflight(ports)

    ensure_python_env()
    ensure_env_file()
    ensure_node_env(npm)

    base_env = os.environ.copy()
    procs: list[tuple[str, subprocess.Popen]] = []

    gateway_env = base_env | {
        "COMMONS_MODE": args.mode,
        "COMMONS_DB": args.db,
        "COMMONS_PORT": str(args.gateway_port),
        "COMMONS_HOST": "127.0.0.1",
    }
    say(f"starting gateway on {args.gateway_port} in {args.mode}")
    procs.append(("gateway", spawn("gateway", [str(VENV_PY), "scripts/run_proxy.py"], ROOT, gateway_env)))

    if want_messaging:
        messaging_env = base_env | {"MESSAGING_PORT": str(MESSAGING_PORT), "MESSAGING_HOST": "127.0.0.1"}
        procs.append(("messaging", spawn(
            "messaging", [str(VENV_PY), "mcp_servers/messaging/run.py"], ROOT, messaging_env)))

    # The dashboard reads the gateway from the browser, so it needs the HOST's view of it.
    dashboard_env = base_env | {
        "NEXT_PUBLIC_COMMONS_URL": f"http://127.0.0.1:{args.gateway_port}",
    }
    # package.json already pins -p 3300. Appending it again works, because Next takes the
    # last one, but it prints "next dev -p 3300 -p 3300" and that reads like a bug.
    dev_command = [npm, "run", "dev"]
    if args.dashboard_port != DASHBOARD_PORT:
        dev_command += ["--", "-p", str(args.dashboard_port)]

    say(f"starting dashboard on {args.dashboard_port}")
    procs.append(("dashboard", spawn("dashboard", dev_command, DASHBOARD, dashboard_env)))

    try:
        # The gateway calls tools/list against every configured vendor before it serves, so
        # a cold start with remote vendors is seconds rather than milliseconds.
        wait_for(f"http://127.0.0.1:{args.gateway_port}/health", "gateway", timeout=90)
        wait_for(f"http://127.0.0.1:{args.dashboard_port}/", "dashboard", timeout=180)

        print(flush=True)
        say(f"dashboard   http://localhost:{args.dashboard_port}")
        say(f"gateway     http://localhost:{args.gateway_port}")
        say("Ctrl+C stops everything")
        print(flush=True)

        while True:
            for name, proc in procs:
                if proc.poll() is not None:
                    say(f"{name} exited with code {proc.returncode}; shutting the rest down")
                    raise KeyboardInterrupt
            time.sleep(1)
    except KeyboardInterrupt:
        print(flush=True)
        say("stopping")
        for _, proc in reversed(procs):
            stop(proc)
        say("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
