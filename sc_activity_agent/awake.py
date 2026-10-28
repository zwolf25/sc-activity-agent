"""Keep the Mac awake while a source-install agent runs. Plans only run while the machine is awake and every sleep shifts the
remaining steps later. The desktop app has its own switch in the tray menu. `caffeinate -w` ends with the agent."""
import os
import subprocess
import sys


def supported():
    return sys.platform == "darwin"


def sync(store, proc):
    """Start or stop caffeinate to match the setting (default on). Returns the process, or None when it is off."""
    if supported() and store.get("keep_awake", True):
        if proc is None or proc.poll() is not None:
            return subprocess.Popen(["caffeinate", "-i", "-s", "-w", str(os.getpid())])
        return proc
    if proc is not None and proc.poll() is None:
        proc.terminate()
    return None
