import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts"
SOURCE = ROOT.parent / "it_vacancies_2024.csv"
BUCKET = "hh-lake"
KEY = "hw3/input/vacancies_core.csv"


@dataclass(frozen=True)
class StorageConfig:
    endpoint: str
    access_key: str
    secret_key: str

    @classmethod
    def load(cls):
        if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
            return cls(
                os.getenv("S3_ENDPOINT", "http://127.0.0.1:9000"),
                os.environ["AWS_ACCESS_KEY_ID"],
                os.environ["AWS_SECRET_ACCESS_KEY"],
            )

        result = subprocess.run(
            ["docker", "inspect", "rustfs-lab"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        env = dict(
            item.split("=", 1)
            for item in json.loads(result.stdout)[0]["Config"]["Env"]
            if "=" in item
        )

        return cls("http://127.0.0.1:9000", env["RUSTFS_ACCESS_KEY"], env["RUSTFS_SECRET_KEY"])
