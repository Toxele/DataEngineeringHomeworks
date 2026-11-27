import yaml

from .config import IMAGE, NAMESPACE, ROOT, save_json


class SchedulingExperiment:
    def __init__(self, cluster):
        self.cluster = cluster

    def resource_pod(self, name, cpu, priority=None, namespace=NAMESPACE):
        specification = {
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 1,
            "containers": [
                {
                    "name": "task",
                    "image": IMAGE,
                    "imagePullPolicy": "Never",
                    "command": ["python", "-c", "import time\ntime.sleep(600)"],
                    "resources": {
                        "requests": {"cpu": cpu, "memory": "32Mi"},
                        "limits": {"cpu": cpu, "memory": "64Mi"},
                    },
                }
            ],
        }

        if priority:
            specification["priorityClassName"] = priority

        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "namespace": namespace},
            "spec": specification,
        }

    def run(self):
        self.cluster.apply("cpu-holder", self.resource_pod("cpu-holder", "7"))
        self.cluster.wait(
            lambda: self.cluster.inspect("pod", "cpu-holder")["status"]["phase"] == "Running"
        )
        self.cluster.apply("cpu-waiting", self.resource_pod("cpu-waiting", "7"))
        self.cluster.wait(
            lambda: any(
                event.get("reason") == "FailedScheduling"
                and "Insufficient cpu" in event.get("message", "")
                for event in self.cluster.inspect("events")["items"]
            )
        )
        self.cluster.snapshot("cpu-pending")
        assert self.cluster.inspect("pod", "cpu-waiting")["status"]["phase"] == "Pending"
        self.cluster.kubectl("delete", "pod", "cpu-holder", "--wait=true")
        self.cluster.wait(
            lambda: self.cluster.inspect("pod", "cpu-waiting")["status"]["phase"] == "Running"
        )
        self.cluster.snapshot("cpu-running")
        self.cluster.kubectl("delete", "pod", "cpu-waiting", "--wait=true")
        priorities = [
            {
                "apiVersion": "scheduling.k8s.io/v1",
                "kind": "PriorityClass",
                "metadata": {"name": f"hw5-{name}"},
                "value": value,
                "globalDefault": False,
                "preemptionPolicy": "PreemptLowerPriority",
            }
            for name, value in (("low", -10), ("high", 1000))
        ]
        self.cluster.apply("priorities", priorities)
        self.cluster.apply("priority-low", self.resource_pod("priority-low", "7", "hw5-low"))
        self.cluster.wait(
            lambda: self.cluster.inspect("pod", "priority-low")["status"]["phase"] == "Running"
        )
        self.cluster.apply("priority-high", self.resource_pod("priority-high", "7", "hw5-high"))
        self.cluster.wait(
            lambda: self.cluster.inspect("pod", "priority-high")["status"]["phase"] == "Running"
        )
        self.cluster.snapshot("preemption")
        events = self.cluster.inspect("events")["items"]
        assert any(
            event.get("reason") == "Preempted" and event["involvedObject"]["name"] == "priority-low"
            for event in events
        )
        self.cluster.kubectl("delete", "pod", "priority-high", "--wait=true")
        self.quota()

    def quota(self):
        quota_namespace = "hw5-quota"
        namespace = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": quota_namespace}}
        quota = {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {"name": "compute", "namespace": quota_namespace},
            "spec": {
                "hard": {
                    "requests.cpu": "1",
                    "requests.memory": "128Mi",
                    "limits.cpu": "1",
                    "limits.memory": "256Mi",
                    "pods": "2",
                }
            },
        }
        self.cluster.apply("quota", [namespace, quota])
        self.cluster.apply(
            "quota-first", self.resource_pod("quota-first", "750m", namespace=quota_namespace)
        )
        self.cluster.wait(
            lambda: (
                self.cluster.inspect("pod", "quota-first", namespace=quota_namespace)["status"][
                    "phase"
                ]
                == "Running"
            )
        )
        rejected = self.resource_pod("quota-second", "750m", namespace=quota_namespace)
        text = yaml.safe_dump(rejected, sort_keys=False)
        (ROOT / "manifests/quota-second.yaml").write_text(text, encoding="utf-8")
        rejection = self.cluster.kubectl(
            "apply", "-f", "-", stdin=text, check=False, namespace=quota_namespace
        )
        assert rejection.returncode and "exceeded quota" in rejection.stderr
        (ROOT / "logs/quota-rejected.txt").write_text(rejection.stderr, encoding="utf-8")
        self.cluster.snapshot("quota", namespace=quota_namespace)
        save_json(
            ROOT / "evidence/quota.json",
            self.cluster.inspect("resourcequota", "compute", namespace=quota_namespace),
        )
        self.cluster.kubectl("delete", "pod", "quota-first", namespace=quota_namespace)
        self.cluster.summary["scheduling"] = {
            "cpu_pending": True,
            "resumed_after_release": True,
            "low_preempted": True,
            "quota_rejected": True,
        }
        self.cluster.persist()
