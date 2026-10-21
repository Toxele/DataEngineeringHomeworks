import json
import platform
import subprocess
import sys
from importlib.metadata import version

import duckdb

from .analysis import Analyst, ResultVerifier
from .config import OUTPUT
from .duckdb_engine import DuckDBEngine
from .mapreduce import MapReduceJob
from .profiling import BenchmarkRunner
from .storage import ObjectStorage, save_json


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    OUTPUT.mkdir(exist_ok=True)

    if stage == "worker":
        method, label = sys.argv[2:4]

        if method == "duckdb":
            result = DuckDBEngine().run(label)
        else:
            result = MapReduceJob(
                combine=method != "mr_plain", inject_failure=method == "mr_retry"
            ).run(label)

        print(json.dumps(result, ensure_ascii=False), flush=True)

        return

    if stage in ("prepare", "all"):
        connection = duckdb.connect()
        connection.execute("INSTALL httpfs")
        connection.close()
        result = ObjectStorage().prepare()
        save_json(OUTPUT / "storage.json", result)
        environment = {
            "python": sys.version,
            "platform": platform.platform(),
            "packages": {p: version(p) for p in ("duckdb", "boto3", "psutil")},
            "docker": subprocess.run(
                ["docker", "version", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout.strip(),
            "rustfs_image": subprocess.run(
                ["docker", "inspect", "rustfs-lab", "--format", "{{.Image}}"],
                capture_output=True,
                text=True,
            ).stdout.strip(),
        }
        save_json(OUTPUT / "environment.json", environment)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    if stage in ("benchmark", "all"):
        runner = BenchmarkRunner()
        runner.run()
        runner.run_one("mr_retry", 1)

    if stage in ("verify", "analyze", "all"):
        ResultVerifier().run()

        if stage != "verify":
            Analyst().run()


if __name__ == "__main__":
    main()
