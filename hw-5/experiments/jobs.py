import json

from .config import IMAGE, NAMESPACE, ROOT, save_json


class CalculationJobs:
    def __init__(self, cluster):
        self.cluster = cluster

    def execute(self, name, memory, mode="full", internal=False, parallelism=None, prefix=None):
        endpoint = "http://s3:9000" if internal else "http://host.docker.internal:9000"
        prefix = prefix or f"hw5/{self.cluster.summary['run']}/{name}"
        environment = {
            "S3_ENDPOINT": endpoint,
            "S3_BUCKET": "hh-lake",
            "MODE": mode,
            "OUTPUT_PREFIX": prefix,
            "PARTS": "3",
        }
        container = {
            "name": "calculation",
            "image": IMAGE,
            "imagePullPolicy": "Never",
            "envFrom": [{"secretRef": {"name": "s3-credentials"}}],
            "env": [{"name": key, "value": value} for key, value in environment.items()],
            "resources": {
                "requests": {"cpu": "500m", "memory": f"{min(memory, 128)}Mi"},
                "limits": {"cpu": "1", "memory": f"{memory}Mi"},
            },
        }
        specification = {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 240,
            "template": {"spec": {"restartPolicy": "Never", "containers": [container]}},
        }

        if parallelism:
            specification.update(
                completions=parallelism,
                parallelism=parallelism,
                completionMode="Indexed",
            )
            container["env"].append(
                {
                    "name": "JOB_COMPLETION_INDEX",
                    "valueFrom": {
                        "fieldRef": {
                            "fieldPath": "metadata.annotations['batch.kubernetes.io/job-completion-index']"
                        }
                    },
                }
            )

        manifest = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": name, "namespace": NAMESPACE},
            "spec": specification,
        }
        self.cluster.apply(name, manifest)
        self.cluster.wait(
            lambda: any(
                condition["type"] in ("Complete", "Failed") and condition["status"] == "True"
                for condition in self.cluster.inspect("job", name)
                .get("status", {})
                .get("conditions", [])
            ),
            timeout=300,
        )
        pods = json.loads(
            self.cluster.kubectl("get", "pods", "-l", f"job-name={name}", "-o", "json").stdout
        )["items"]
        records = []

        for pod in pods:
            pod_name = pod["metadata"]["name"]
            output = self.cluster.kubectl("logs", pod_name).stdout
            (ROOT / "logs" / f"{pod_name}.txt").write_text(output, encoding="utf-8")
            completed = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
            records.append(
                {
                    "pod": pod_name,
                    "status": pod["status"],
                    "result": next(
                        (row for row in completed if row.get("event") == "completed"), None
                    ),
                }
            )

        save_json(ROOT / "evidence" / f"{name}.json", records)
        self.cluster.snapshot(name)

        return prefix, records
