from __future__ import annotations
import os
import subprocess
import time
import psutil

class NiceHashManager:
    def __init__(self, executable: str, working_directory: str, process_name: str, startup_timeout: int, stop_timeout: int):
        self.executable = executable
        self.working_directory = working_directory
        self.process_name = process_name.lower()
        # NiceHashMiner.exe acts as a watchdog around the actual app process
        # (process_name, e.g. app_nhm.exe): if only the app process is killed,
        # the watchdog respawns it within seconds. Both must be stopped.
        self.launcher_name = os.path.basename(executable).lower()
        self.startup_timeout = startup_timeout
        self.stop_timeout = stop_timeout
        self._process = None

    def _find(self, name: str):
        found = []
        for p in psutil.process_iter(["name"]):
            try:
                if (p.info["name"] or "").lower() == name:
                    found.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found

    def is_running(self) -> bool:
        return bool(self._find(self.process_name))

    def start(self) -> bool:
        if self.is_running():
            return True
        if not os.path.isfile(self.executable):
            raise FileNotFoundError(self.executable)
        self._process = subprocess.Popen([self.executable], cwd=self.working_directory)
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self.is_running():
                return True
            time.sleep(1)
        return self.is_running()

    def _terminate_all(self, name: str):
        procs = self._find(name)
        for p in procs:
            try:
                p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        gone, alive = psutil.wait_procs(procs, timeout=self.stop_timeout)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def stop(self) -> bool:
        # Stop the watchdog first so it can't respawn the app process while
        # we're shutting it down, then stop the app process itself.
        if self.launcher_name != self.process_name:
            self._terminate_all(self.launcher_name)
        self._terminate_all(self.process_name)
        return not self.is_running() and not self._find(self.launcher_name)
