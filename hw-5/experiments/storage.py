import csv
import hashlib
import io

from .config import NAMESPACE, ROOT, RUSTFS


class StorageMigration:
    def __init__(self, cluster):
        self.cluster = cluster

    def run(self):
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "s3", "namespace": NAMESPACE},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "hw5-s3"}},
                "template": {
                    "metadata": {"labels": {"app": "hw5-s3"}},
                    "spec": {
                        "securityContext": {"fsGroup": 10001},
                        "containers": [
                            {
                                "name": "s3",
                                "image": RUSTFS,
                                "env": [
                                    {
                                        "name": "RUSTFS_ACCESS_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "s3-credentials",
                                                "key": "AWS_ACCESS_KEY_ID",
                                            }
                                        },
                                    },
                                    {
                                        "name": "RUSTFS_SECRET_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "s3-credentials",
                                                "key": "AWS_SECRET_ACCESS_KEY",
                                            }
                                        },
                                    },
                                    {"name": "RUSTFS_VOLUMES", "value": "/data"},
                                    {"name": "RUSTFS_ADDRESS", "value": ":9000"},
                                    {"name": "RUSTFS_CONSOLE_ENABLE", "value": "false"},
                                ],
                                "ports": [{"containerPort": 9000}],
                                "readinessProbe": {
                                    "tcpSocket": {"port": 9000},
                                    "initialDelaySeconds": 5,
                                },
                                "resources": {
                                    "requests": {"cpu": "250m", "memory": "256Mi"},
                                    "limits": {"cpu": "2", "memory": "1Gi"},
                                },
                                "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                            }
                        ],
                        "volumes": [
                            {"name": "data", "persistentVolumeClaim": {"claimName": "s3-data"}}
                        ],
                    },
                },
            },
        }
        pvc = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": "s3-data", "namespace": NAMESPACE},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "2Gi"}},
            },
        }
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "s3", "namespace": NAMESPACE},
            "spec": {"selector": {"app": "hw5-s3"}, "ports": [{"port": 9000, "targetPort": 9000}]},
        }
        self.cluster.apply("s3", [pvc, deployment, service])
        self.cluster.kubectl("rollout", "status", "deployment/s3", "--timeout=180s")
        source = ROOT.parent / "hw-3/artifacts/input/vacancies_core.csv"
        original = self.cluster.storage("http://127.0.0.1:9000")
        key = "hw3/input/vacancies_core.csv"
        remote = original.get_object(Bucket="hh-lake", Key=key)["Body"].read()
        assert hashlib.sha256(remote).hexdigest() == hashlib.sha256(source.read_bytes()).hexdigest()

        with self.cluster.forwarded_storage() as storage:
            storage.create_bucket(Bucket="hh-lake")
            storage.put_object(Bucket="hh-lake", Key=key, Body=remote)
            streams = [io.StringIO(newline="") for _ in range(3)]
            sizes = [0, 0, 0]

            with source.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                writers = [csv.DictWriter(part, fieldnames=reader.fieldnames) for part in streams]

                for writer in writers:
                    writer.writeheader()

                for index, row in enumerate(reader):
                    part = index % 3
                    writers[part].writerow(row)
                    sizes[part] += 1

            for index, stream in enumerate(streams):
                storage.put_object(
                    Bucket="hh-lake",
                    Key=f"hw5/input/part-{index:03}.csv",
                    Body=stream.getvalue().encode("utf-8"),
                )

            copied = storage.get_object(Bucket="hh-lake", Key=key)["Body"].read()
            assert copied == remote

        self.cluster.summary["storage"] = {
            "image": RUSTFS,
            "service": "http://s3:9000",
            "pvc": "s3-data",
            "input_bytes": len(remote),
            "input_sha256": hashlib.sha256(remote).hexdigest(),
            "parts_rows": sizes,
            "copied_bytes_equal": True,
        }
        self.cluster.persist()
        self.cluster.snapshot("s3")
