import csv
import hashlib
import io

from .config import ROOT
from .jobs import CalculationJobs


class ParallelCalculation:
    def __init__(self, cluster):
        self.cluster = cluster
        self.jobs = CalculationJobs(cluster)

    @staticmethod
    def counts(stream):
        return {
            (row["skill_1"], row["skill_2"]): int(row["frequency"])
            for row in csv.DictReader(stream)
        }

    def run(self):
        limit = self.cluster.summary["memory"]["chosen_limit_mib"]
        prefix, workers = self.jobs.execute(
            "parallel", limit, mode="part", internal=True, parallelism=3
        )
        assert all(worker["status"]["phase"] == "Succeeded" for worker in workers)
        assert sum(worker["result"]["rows"] for worker in workers) == 229388
        assert sum(worker["result"]["selected"] for worker in workers) == 18698
        _, records = self.jobs.execute("reduce", limit, mode="reduce", internal=True, prefix=prefix)
        assert records[0]["result"], records
        self.cluster.summary["parallel"] = {"workers": workers, "reducer": records[0]["result"]}
        self.cluster.persist()
        self.verify(prefix)

    def verify(self, prefix):
        reference = ROOT.parent / "hw-3/artifacts/mr_combiner_1/skills_2.csv"

        with reference.open(encoding="utf-8", newline="") as stream:
            expected = self.counts(stream)

        with self.cluster.forwarded_storage() as storage:
            result = storage.get_object(Bucket="hh-lake", Key=f"{prefix}/skills_2.csv")[
                "Body"
            ].read()

        actual = self.counts(io.StringIO(result.decode("utf-8")))
        assert expected == actual
        (ROOT / "artifacts/skills_2.csv").write_bytes(result)
        top = sorted(actual.items(), key=lambda item: (-item[1], item[0]))[:10]
        with (ROOT / "evidence/top10.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["skill_1", "skill_2", "hw3_frequency", "kubernetes_frequency"])
            writer.writerows([*pair, expected[pair], count] for pair, count in top)
        self.cluster.summary["verification"] = {
            "all_frequencies_equal": True,
            "keys": len(actual),
            "occurrences": sum(actual.values()),
            "sha256": hashlib.sha256(result).hexdigest(),
            "top10": [{"skills": list(pair), "frequency": count} for pair, count in top],
        }
        self.cluster.persist()
