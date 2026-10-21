import csv
import itertools
import json
import statistics
from collections import Counter, defaultdict

from .config import OUTPUT
from .storage import ObjectStorage, save_json


def read_counts(directory, size):
    with (directory / f"skills_{size}.csv").open(encoding="utf-8", newline="") as stream:
        return {
            tuple(row[f"skill_{i}"] for i in range(1, size + 1)): int(row["frequency"])
            for row in csv.DictReader(stream)
        }


def read_vacancies(directory):
    with (directory / "vacancies.csv").open(encoding="utf-8", newline="") as stream:
        return {
            row["vacancy_id"]: (
                row["region"],
                tuple(json.loads(row["skills"])),
                float(row["salary"]) if row["salary"] else None,
            )
            for row in csv.DictReader(stream)
        }


class ResultVerifier:
    def run(self):
        reference = OUTPUT / "mr_combiner_1"
        expected_rows = read_vacancies(reference)

        if (
            len(expected_rows)
            != json.loads((reference / "summary.json").read_text(encoding="utf-8"))["selected_rows"]
        ):
            raise AssertionError("Duplicate vacancy IDs in selected data")

        checks = []

        for directory in sorted(OUTPUT.iterdir()):
            if not directory.is_dir() or not (directory / "skills_1.csv").exists():
                continue

            for size in (1, 2, 3):
                expected = read_counts(reference, size)
                actual = read_counts(directory, size)

                if expected != actual:
                    missing = list((expected.keys() ^ actual.keys()))[:5]
                    changed = [
                        k for k in expected.keys() & actual.keys() if expected[k] != actual[k]
                    ][:5]
                    raise AssertionError(
                        f"{directory.name}: size={size}, missing={missing}, changed={changed}"
                    )

                checks.append(
                    {
                        "run": directory.name,
                        "stack_size": size,
                        "keys": len(actual),
                        "occurrences": sum(actual.values()),
                        "equal": True,
                    }
                )

            if read_vacancies(directory) != expected_rows:
                raise AssertionError(f"Vacancy-level disagreement: {directory.name}")

        expected_emissions = {
            str(k): sum(
                sum(1 for _ in itertools.combinations(v[1], k)) for v in expected_rows.values()
            )
            for k in (1, 2, 3)
        }
        save_json(
            OUTPUT / "verification.json",
            {
                "all_equal": True,
                "checks": checks,
                "vacancy_level_equal": True,
                "expected_emissions": expected_emissions,
            },
        )
        print(
            f"VERIFIED: {len(checks)} full key-frequency comparisons; "
            "vacancy rows, skills, salaries match.",
            flush=True,
        )


class Analyst:
    MIN_SUPPORT = 30

    @staticmethod
    def write_csv(path, rows):
        if not rows:
            return

        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def run(self):
        vacancies = read_vacancies(OUTPUT / "mr_combiner_1")
        counts = {
            key: value
            for size in (1, 2, 3)
            for key, value in read_counts(OUTPUT / "mr_combiner_1", size).items()
        }
        salaries = defaultdict(list)
        region_rows = defaultdict(list)

        for region, skills, salary in vacancies.values():
            region_rows[region].append((skills, salary))

            if salary is not None:
                for size in (1, 2, 3):
                    for key in itertools.combinations(skills, size):
                        salaries[key].append(salary)

        medians = {key: statistics.median(values) for key, values in salaries.items()}
        impacts = []

        for key in counts:
            if len(key) < 2 or len(salaries[key]) < self.MIN_SUPPORT:
                continue

            base = min(itertools.combinations(key, len(key) - 1), key=lambda k: (-counts[k], k))
            anchor = min(((skill,) for skill in key), key=lambda k: (-counts[k], k))
            median = medians[key]
            impacts.append(
                {
                    "stack_size": len(key),
                    "skills": " + ".join(key),
                    "frequency": counts[key],
                    "salary_n": len(salaries[key]),
                    "median_rub": median,
                    "base": " + ".join(base),
                    "base_frequency": counts[base],
                    "base_salary_n": len(salaries[base]),
                    "base_median_rub": medians[base],
                    "added_skill": next(iter(set(key) - set(base))),
                    "delta_rub": median - medians[base],
                    "delta_pct": (median / medians[base] - 1) * 100,
                    "anchor_skill": anchor[0],
                    "anchor_frequency": counts[anchor],
                    "anchor_salary_n": len(salaries[anchor]),
                    "anchor_median_rub": medians[anchor],
                    "delta_anchor_pct": (median / medians[anchor] - 1) * 100,
                }
            )

        impacts.sort(key=lambda r: (r["stack_size"], -r["delta_pct"], -r["salary_n"], r["skills"]))
        directory = OUTPUT / "analysis"
        directory.mkdir(exist_ok=True)
        self.write_csv(directory / "salary_impacts.csv", impacts)
        rankings = {}

        for size in (2, 3):
            for direction in ("increase", "decrease"):
                subset = [
                    r
                    for r in impacts
                    if r["stack_size"] == size
                    and (r["delta_rub"] > 0 if direction == "increase" else r["delta_rub"] < 0)
                ]
                subset.sort(
                    key=lambda r: (
                        (-1 if direction == "increase" else 1) * r["delta_pct"],
                        -r["salary_n"],
                        r["skills"],
                    )
                )
                rankings[f"{size}_{direction}"] = subset[:5]

        chosen_regions = [
            region
            for region, _ in sorted(region_rows.items(), key=lambda item: (-len(item[1]), item[0]))[
                :3
            ]
        ]
        region_stats = []
        region_stacks = []

        for region in chosen_regions:
            rows = region_rows[region]
            known = [salary for _, salary in rows if salary is not None]
            frequency = Counter(
                key
                for skills, _ in rows
                for size in (1, 2, 3)
                for key in itertools.combinations(skills, size)
            )
            region_stats.append(
                {
                    "region": region,
                    "vacancies": len(rows),
                    "with_skills": sum(bool(s) for s, _ in rows),
                    "salary_n": len(known),
                    "salary_coverage_pct": 100 * len(known) / len(rows),
                    "median_rub": statistics.median(known),
                    **{f"with_stack_{k}": sum(len(s) >= k for s, _ in rows) for k in (1, 2, 3)},
                    **{
                        f"combinations_{k}": sum(v for key, v in frequency.items() if len(key) == k)
                        for k in (1, 2, 3)
                    },
                }
            )

            for size in (1, 2, 3):
                top = sorted(
                    ((key, v) for key, v in frequency.items() if len(key) == size),
                    key=lambda item: (-item[1], item[0]),
                )[:5]

                for key, count in top:
                    region_stacks.append(
                        {
                            "region": region,
                            "stack_size": size,
                            "skills": " + ".join(key),
                            "frequency": count,
                            "vacancy_share_pct": 100 * count / len(rows),
                        }
                    )

        self.write_csv(directory / "regions.csv", region_stats)
        self.write_csv(directory / "region_stacks.csv", region_stacks)
        skill_histogram = Counter(len(skills) for _, skills, _ in vacancies.values())
        summary = {
            "min_salary_support": self.MIN_SUPPORT,
            "regions": region_stats,
            "region_stacks": region_stacks,
            "rankings": rankings,
            "skill_count_histogram": dict(sorted(skill_histogram.items())),
            "overall_median_rub": statistics.median(
                [v[2] for v in vacancies.values() if v[2] is not None]
            ),
            "top_frequencies": {
                str(size): [
                    {"skills": " + ".join(key), "frequency": count}
                    for key, count in sorted(
                        ((key, v) for key, v in counts.items() if len(key) == size),
                        key=lambda item: (-item[1], item[0]),
                    )[:10]
                ]
                for size in (1, 2, 3)
            },
        }
        save_json(OUTPUT / "analysis.json", summary)
        storage = ObjectStorage()
        manifest = storage.upload_results(OUTPUT / "mr_combiner_1")
        manifest += storage.upload_results(directory)
        save_json(OUTPUT / "s3_outputs.json", manifest)
        print(
            json.dumps({"regions": region_stats, "s3_objects": len(manifest)}, ensure_ascii=False),
            flush=True,
        )
