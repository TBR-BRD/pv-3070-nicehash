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
        self.startup_timeout = startup_timeout
        self.stop_timeout = stop_timeout
        self._process = None

    def is_running(self) -> bool:
        for p in psutil.process_iter(["name"]):
            try:
                if (p.info["name"] or "").lower() == self.process_name:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

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

    def stop(self) -> bool:
        procs = []
        for p in psutil.process_iter(["name"]):
            try:
                if (p.info["name"] or "").lower() == self.process_name:
                    procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
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
        return not self.is_running()
