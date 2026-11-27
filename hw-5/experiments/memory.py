import math

from .jobs import CalculationJobs


class MemoryExperiment:
    def __init__(self, cluster):
        self.cluster = cluster
        self.jobs = CalculationJobs(cluster)

    def run(self):
        _, profile = self.jobs.execute("memory-profile", 512)
        assert profile[0]["status"]["phase"] == "Succeeded"
        measurement = profile[0]["result"]["memory"]
        peak = measurement["cgroup_peak_bytes"] or measurement["rss_peak_bytes"]
        peak_mib = peak / 1024**2
        low = max(32, math.floor(peak_mib * 0.6 / 8) * 8)
        _, failed = self.jobs.execute("memory-oom", low)
        termination = failed[0]["status"]["containerStatuses"][0]["state"]["terminated"]
        assert termination["reason"] == "OOMKilled", termination
        limit = math.ceil(peak_mib * 1.25 / 16) * 16
        _, tuned = self.jobs.execute("memory-tuned", limit)
        assert tuned[0]["status"]["phase"] == "Succeeded"
        assert tuned[0]["result"]["sha256"] == profile[0]["result"]["sha256"]
        self.cluster.summary["memory"] = {
            "profile": profile[0]["result"],
            "peak_mib": peak_mib,
            "oom_limit_mib": low,
            "oom_reason": termination["reason"],
            "oom_exit_code": termination["exitCode"],
            "chosen_limit_mib": limit,
            "tuned": tuned[0]["result"],
        }
        self.cluster.persist()
