import hashlib
import json
import os
import resource
import time
from pathlib import Path

from .processing import PairCalculation
from .storage import ObjectStorage


class MemoryUsage:
    @staticmethod
    def read(name: str):
        path = Path("/sys/fs/cgroup") / name

        if path.exists():
            value = path.read_text().strip()

            if value.isdigit():
                return int(value)

        return None

    @classmethod
    def snapshot(cls):
        return {
            "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "cgroup_peak_bytes": cls.read("memory.peak"),
            "cgroup_limit_bytes": cls.read("memory.max"),
        }


class BatchJob:
    def run(self):
        mode = os.environ.get("MODE", "full")
        storage = ObjectStorage()
        calculation = PairCalculation()
        prefix = os.environ.get("OUTPUT_PREFIX", "hw5/full")
        parts = int(os.environ.get("PARTS", "3"))
        index = int(os.environ.get("JOB_COMPLETION_INDEX", "0"))
        started = time.monotonic()
        print(json.dumps({"event": "started", "mode": mode, "index": index}), flush=True)

        if mode == "reduce":
            for part in range(parts):
                calculation.merge(storage.rows(f"{prefix}/parts/{part}.csv"))
        else:
            key = (
                f"hw5/input/part-{index:03}.csv"
                if mode == "part"
                else "hw3/input/vacancies_core.csv"
            )
            calculation.consume(storage.rows(key))

        body = calculation.csv()
        key = f"{prefix}/parts/{index}.csv" if mode == "part" else f"{prefix}/skills_2.csv"
        storage.put(key, body)
        result = {
            "event": "completed",
            "mode": mode,
            "index": index,
            "rows": calculation.rows,
            "selected": calculation.selected,
            "keys": len(calculation.counts),
            "occurrences": sum(calculation.counts.values()),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "seconds": round(time.monotonic() - started, 3),
            "memory": MemoryUsage.snapshot(),
            "top10": calculation.top(),
        }
        storage.put_json(f"{prefix}/stats-{mode}-{index}.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    BatchJob().run()
