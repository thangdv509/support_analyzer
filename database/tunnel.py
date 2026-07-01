"""
SSH tunnel manager for MongoDB access.

Opens an SSH tunnel in the background on startup and closes it on exit.
Config is read from .env (SSH_TUNNEL_* vars).

Usage:
    from database.tunnel import ensure_tunnel
    ensure_tunnel()   # idempotent — safe to call multiple times
"""

import os
import socket
import subprocess
import threading
import time
import atexit
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

_tunnel_proc: subprocess.Popen | None = None
_watchdog_thread: threading.Thread | None = None


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def ensure_tunnel() -> bool:
    """
    Start the SSH tunnel if not already reachable.
    Returns True if tunnel is ready, False if it failed to start.
    """
    global _tunnel_proc

    host = os.getenv("MONGO_HOST", "127.0.0.1")
    port = int(os.getenv("MONGO_PORT", "27018"))

    # Already open (e.g. user started it manually or called before)
    if _port_open(host, port):
        return True

    ssh_host   = os.getenv("SSH_TUNNEL_HOST")
    ssh_port   = os.getenv("SSH_TUNNEL_PORT", "22")
    ssh_user   = os.getenv("SSH_TUNNEL_USER", "bastion")
    ssh_key    = os.getenv("SSH_TUNNEL_KEY")
    ssh_remote = os.getenv("SSH_TUNNEL_REMOTE")  # e.g. "10.136.244.62:27017"

    if not all([ssh_host, ssh_remote]):
        print("⚠️  SSH_TUNNEL_HOST / SSH_TUNNEL_REMOTE not set in .env — skipping tunnel")
        return False

    # Kill any stale ssh process holding the local port
    try:
        result = subprocess.run(["fuser", f"{port}/tcp"], capture_output=True, text=True)
        pids = result.stdout.split()
        for pid in pids:
            subprocess.run(["kill", pid], capture_output=True)
        if pids:
            time.sleep(0.5)
    except Exception:
        pass

    remote_host, remote_port = ssh_remote.rsplit(":", 1)
    local_fwd = f"{port}:{remote_host}:{remote_port}"

    cmd = [
        "ssh", "-N", "-L", local_fwd,
        "-p", ssh_port,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "TCPKeepAlive=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=10",
    ]
    if ssh_key:
        cmd += ["-i", ssh_key]
    cmd.append(f"{ssh_user}@{ssh_host}")

    import tempfile
    _stderr_file = tempfile.NamedTemporaryFile(delete=False, suffix=".log", mode="w")
    print(f"🔌 Opening SSH tunnel → {ssh_remote} via {ssh_user}@{ssh_host}:{ssh_port}")
    _tunnel_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=_stderr_file)
    atexit.register(_close_tunnel)

    # Wait up to 15s for port to become available
    for _ in range(30):
        time.sleep(0.5)
        if _port_open(host, port):
            print(f"   ✅ Tunnel ready on {host}:{port}")
            _stderr_file.close()
            _start_watchdog()
            return True

    _stderr_file.flush()
    _stderr_file.close()
    try:
        with open(_stderr_file.name) as f:
            err = f.read().strip()
        if err:
            print(f"   SSH error: {err}")
    except Exception:
        pass

    print(f"   ❌ Tunnel did not open in time")
    _close_tunnel()
    return False


def _start_watchdog():
    """Start a background thread that restarts the tunnel if the SSH process dies."""
    global _watchdog_thread
    if _watchdog_thread and _watchdog_thread.is_alive():
        return

    def _watch():
        while True:
            time.sleep(30)
            if _tunnel_proc is not None and _tunnel_proc.poll() is not None:
                print("⚠️  SSH tunnel process died — restarting...")
                ensure_tunnel()

    _watchdog_thread = threading.Thread(target=_watch, daemon=True, name="tunnel-watchdog")
    _watchdog_thread.start()


def _close_tunnel():
    global _tunnel_proc
    if _tunnel_proc and _tunnel_proc.poll() is None:
        _tunnel_proc.terminate()
        _tunnel_proc = None
