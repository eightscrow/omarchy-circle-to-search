"""Single-instance lock via fcntl + PID tracking."""

import fcntl
import json
import os
import subprocess
import sys
import time

_INSTANCE_LOCK_FILE = None


def _current_script_path():
    if not sys.argv:
        return ""
    return os.path.realpath(sys.argv[0])


def _proc_start_time(pid):
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
            return f.read().split()[21]
    except (OSError, IndexError):
        return None


def _read_lock_metadata(lock_path):
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return None
        if content.isdigit():
            return {"pid": int(content), "legacy": True}
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _write_lock_metadata(lock_file):
    metadata = {
        "pid": os.getpid(),
        "script": _current_script_path(),
        "start_time": _proc_start_time(os.getpid()),
    }
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(json.dumps(metadata))
    lock_file.flush()


def _kill_stale_instance(lock_path):
    """Kill a stale instance whose PID is still in the lock file."""
    try:
        metadata = _read_lock_metadata(lock_path)
        if not metadata:
            return False

        old_pid = int(metadata.get("pid", 0))
        legacy = bool(metadata.get("legacy"))
        old_script = metadata.get("script", "")
        old_start_time = str(metadata.get("start_time", ""))
        if old_pid <= 0:
            return False

        if legacy:
            cmdline_path = f"/proc/{old_pid}/cmdline"
            if not os.path.exists(cmdline_path):
                return True
            with open(cmdline_path, "rb") as f:
                cmdline = f.read().decode(errors="replace")
            if "circle-to-search" in cmdline:
                os.kill(old_pid, 15)
                for _ in range(10):
                    if not os.path.exists(f"/proc/{old_pid}"):
                        return True
                    time.sleep(0.1)
                os.kill(old_pid, 9)
                return True
            return False

        if not old_script or not old_start_time:
            return False

        cmdline_path = f"/proc/{old_pid}/cmdline"
        if os.path.exists(cmdline_path):
            current_start_time = _proc_start_time(old_pid)
            if current_start_time != old_start_time:
                return True

            with open(cmdline_path, "rb") as f:
                cmdline = [part.decode(errors="replace") for part in f.read().split(b"\0") if part]
            if old_script in cmdline:
                os.kill(old_pid, 15)  # SIGTERM
                for _ in range(10):
                    if not os.path.exists(f"/proc/{old_pid}"):
                        return True
                    time.sleep(0.1)
                os.kill(old_pid, 9)  # SIGKILL
                return True
        return False
    except (ValueError, OSError, ProcessLookupError):
        return True


def _try_lock(lock_path):
    """Attempt to acquire the flock. Returns True on success."""
    global _INSTANCE_LOCK_FILE
    lock_file = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _write_lock_metadata(lock_file)
        _INSTANCE_LOCK_FILE = lock_file
        return True
    except OSError:
        lock_file.close()
        return False


def acquire():
    """Prevent overlapping launches from rapid key presses.
    Returns True if lock acquired, False otherwise."""
    lock_path = "/tmp/circle-to-search.lock"
    if _try_lock(lock_path):
        return True
    if _kill_stale_instance(lock_path) and _try_lock(lock_path):
        return True
    subprocess.run(
        ["notify-send", "-t", "1500", "Circle to Search", "Already running"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return False


def release():
    """Release the single-instance lock."""
    global _INSTANCE_LOCK_FILE
    if _INSTANCE_LOCK_FILE is None:
        return
    try:
        fcntl.flock(_INSTANCE_LOCK_FILE, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        _INSTANCE_LOCK_FILE.close()
    except OSError:
        pass
    _INSTANCE_LOCK_FILE = None
