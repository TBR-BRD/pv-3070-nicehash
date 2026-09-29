from __future__ import annotations
import subprocess


class WindowsPower:
    """Thin wrapper around the Windows `shutdown` command."""

    def shutdown(self, delay_seconds: int = 60) -> None:
        # A short delay (instead of /t 0) leaves a window to cancel via
        # `shutdown /a` if this ever triggers unexpectedly.
        subprocess.run(["shutdown", "/s", "/t", str(delay_seconds)], check=False)

    def cancel_shutdown(self) -> None:
        subprocess.run(["shutdown", "/a"], check=False)
