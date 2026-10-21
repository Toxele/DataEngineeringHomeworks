import csv
import json

import duckdb

from .config import BUCKET, KEY, OUTPUT, ROOT, StorageConfig
from .storage import save_json


def quote_sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class DuckDBEngine:
    def __init__(self):
        self.connection = duckdb.connect(
            config={
                "threads": 2,
                "memory_limit": "512MB",
                "temp_directory": str(OUTPUT / "duckdb-temp"),
            }
        )
        self.connection.execute("LOAD httpfs")
        config = StorageConfig.load()
        self.connection.execute(f"""CREATE SECRET rustfs (
            TYPE s3, KEY_ID {quote_sql(config.access_key)}, SECRET {quote_sql(config.secret_key)},
            REGION 'us-east-1', ENDPOINT {quote_sql(config.endpoint.removeprefix("http://"))},
            URL_STYLE 'path', USE_SSL false)""")

    def run(self, label: str):
        sql = (ROOT / "sql" / "frequencies.sql").read_text(encoding="utf-8")
        self.connection.execute(sql.replace("__INPUT__", f"s3://{BUCKET}/{KEY}"))
        target = OUTPUT / label
        target.mkdir(parents=True, exist_ok=True)

        for size in (1, 2, 3):
            rows = self.connection.execute(
                "SELECT skills, frequency FROM frequencies WHERE len(skills)=? ORDER BY skills",
                [size],
            ).fetchall()

            with (target / f"skills_{size}.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow([f"skill_{i}" for i in range(1, size + 1)] + ["frequency"])
                writer.writerows([*skills, count] for skills, count in rows)

        rows = self.connection.execute(
            "SELECT vacancy_id, region, skills, salary FROM vacancies ORDER BY vacancy_id"
        ).fetchall()

        with (target / "vacancies.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["vacancy_id", "region", "skills", "salary"])
            writer.writerows((v, r, json.dumps(s, ensure_ascii=False), p) for v, r, s, p in rows)

        summary = {
            "input_rows": self.connection.execute("SELECT count(*) FROM raw").fetchone()[0],
            "selected_rows": len(rows),
            "with_skills": sum(bool(row[2]) for row in rows),
            "salary_rows": sum(row[3] is not None for row in rows),
        }
        save_json(target / "summary.json", summary)
        self.connection.close()

        return summary
