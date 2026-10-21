import csv
import json
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations

from .config import OUTPUT
from .domain import VacancyPolicy
from .storage import ObjectStorage, save_json


class SkillMapper:
    @staticmethod
    def execute(rows: list[dict], combine: bool, fail: bool = False):
        if fail:
            raise RuntimeError("Injected transient mapper failure before commit")

        counts = Counter() if combine else []
        selected = []

        for row in rows:
            if not VacancyPolicy.matches(row):
                continue

            vacancy = VacancyPolicy.parse(row)
            selected.append(vacancy)

            for size in (1, 2, 3):
                emitted = combinations(vacancy.skills, size)

                if combine:
                    counts.update(emitted)
                else:
                    counts.extend(emitted)

        return counts, selected


class MapReduceJob:
    def __init__(
        self, combine: bool, chunk_size: int = 2000, workers: int = 2, inject_failure: bool = False
    ):
        self.combine = combine
        self.chunk_size = chunk_size
        self.workers = workers
        self.inject_failure = inject_failure

    def run(self, label: str):
        counts = Counter()
        vacancies = []
        rows_read = 0
        attempts = []
        pending = deque()

        def commit(item):
            chunk_id, rows, future = item

            try:
                partial, selected = future.result()
            except RuntimeError as error:
                attempts.append(
                    {"chunk": chunk_id, "attempt": 1, "status": "failed", "error": str(error)}
                )
                partial, selected = executor.submit(
                    SkillMapper.execute, rows, self.combine
                ).result()
                attempts.append({"chunk": chunk_id, "attempt": 2, "status": "committed"})

            counts.update(partial)
            vacancies.extend(selected)

        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            chunk = []
            chunk_id = 0

            for row in ObjectStorage().rows():
                rows_read += 1

                chunk.append(
                    {
                        k: row[k]
                        for k in (
                            "vacancy_id",
                            "name",
                            "role",
                            "area",
                            "key_skills",
                            "salary_from",
                            "salary_to",
                            "currency",
                            "gross",
                        )
                    }
                )

                if len(chunk) < self.chunk_size:
                    continue

                pending.append(
                    (
                        chunk_id,
                        chunk,
                        executor.submit(
                            SkillMapper.execute,
                            chunk,
                            self.combine,
                            self.inject_failure and chunk_id == 2,
                        ),
                    )
                )
                chunk_id += 1
                chunk = []

                if len(pending) >= self.workers * 2:
                    commit(pending.popleft())

            if chunk:
                pending.append(
                    (chunk_id, chunk, executor.submit(SkillMapper.execute, chunk, self.combine))
                )

            while pending:
                commit(pending.popleft())

        target = OUTPUT / label
        target.mkdir(parents=True, exist_ok=True)

        for size in (1, 2, 3):
            with (target / f"skills_{size}.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow([f"skill_{i}" for i in range(1, size + 1)] + ["frequency"])
                writer.writerows(
                    [*key, value] for key, value in sorted(counts.items()) if len(key) == size
                )

        with (target / "vacancies.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["vacancy_id", "region", "skills", "salary"])
            writer.writerows(
                (v.identifier, v.region, json.dumps(v.skills, ensure_ascii=False), v.salary)
                for v in vacancies
            )

        summary = {
            "input_rows": rows_read,
            "selected_rows": len(vacancies),
            "with_skills": sum(bool(v.skills) for v in vacancies),
            "salary_rows": sum(v.salary is not None for v in vacancies),
            "unique": {str(k): sum(len(key) == k for key in counts) for k in (1, 2, 3)},
            "emitted": {
                str(k): sum(v for key, v in counts.items() if len(key) == k) for k in (1, 2, 3)
            },
            "chunk_size": self.chunk_size,
            "workers": self.workers,
            "attempts": attempts,
        }
        save_json(target / "summary.json", summary)

        return summary
