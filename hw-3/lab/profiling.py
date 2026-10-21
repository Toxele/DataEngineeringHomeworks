import json
import os
import subprocess
import sys
import threading
import time

import psutil

from .config import OUTPUT, ROOT
from .storage import save_json


class BenchmarkRunner:
    def run_one(self, method: str, attempt: int):
        label = f"{method}_{attempt}"
        log_path = OUTPUT / "logs" / f"{label}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        docker_samples = []
        stop = threading.Event()

        def sample_server():
            while not stop.is_set():
                result = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{json .}}", "rustfs-lab"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )

                if result.returncode == 0:
                    docker_samples.append(
                        {
                            "elapsed_s": time.perf_counter() - start,
                            "stats": json.loads(result.stdout),
                        }
                    )

                stop.wait(1)

        start = time.perf_counter()
        monitor = threading.Thread(target=sample_server, daemon=True)
        monitor.start()
        peak = 0
        samples = 0
        cpu_times = {}

        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lab", "worker", method, label],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=os.environ.copy(),
            )
            parent = psutil.Process(process.pid)

            while process.poll() is None:
                try:
                    total = 0

                    for child in [parent, *parent.children(recursive=True)]:
                        try:
                            total += child.memory_info().rss
                            cpu = child.cpu_times()
                            cpu_times[child.pid] = cpu.user + cpu.system
                        except psutil.Error:
                            pass

                    peak = max(peak, total)
                    samples += 1
                except psutil.Error:
                    pass

                time.sleep(0.02)

        elapsed = time.perf_counter() - start
        stop.set()
        monitor.join(timeout=8)
        result = {
            "method": method,
            "attempt": attempt,
            "label": label,
            "wall_s": elapsed,
            "peak_tree_rss_mib": peak / 1024**2,
            "cpu_s_sampled": sum(cpu_times.values()),
            "rss_samples": samples,
            "server_samples": docker_samples,
            "exit_code": process.returncode,
        }
        save_json(OUTPUT / "profiles" / f"{label}.json", result)

        if process.returncode:
            raise RuntimeError(f"{label} failed: see {log_path}")

        print(json.dumps({k: v for k, v in result.items() if k != "server_samples"}), flush=True)

        return result

    def run(self):
        results = []

        for attempt, methods in enumerate(
            [
                ("mr_plain", "mr_combiner", "duckdb"),
                ("duckdb", "mr_plain", "mr_combiner"),
                ("mr_combiner", "duckdb", "mr_plain"),
            ],
            1,
        ):
            for method in methods:
                results.append(self.run_one(method, attempt))

        save_json(OUTPUT / "benchmarks.json", results)
