import json
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import boto3
import yaml
from botocore.config import Config

from .config import IMAGE, NAMESPACE, ROOT, save_json


class Cluster:
    def __init__(self):
        for directory in ("logs", "evidence", "manifests", "artifacts"):
            (ROOT / directory).mkdir(exist_ok=True)

        self.summary_path = ROOT / "evidence/summary.json"
        self.summary = (
            json.loads(self.summary_path.read_text(encoding="utf-8"))
            if self.summary_path.exists()
            else {"run": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")}
        )
        result = subprocess.run(
            ["docker", "inspect", "rustfs-lab"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        environment = dict(
            item.split("=", 1)
            for item in json.loads(result.stdout)[0]["Config"]["Env"]
            if "=" in item
        )
        self.credentials = {
            "AWS_ACCESS_KEY_ID": environment["RUSTFS_ACCESS_KEY"],
            "AWS_SECRET_ACCESS_KEY": environment["RUSTFS_SECRET_KEY"],
        }

    def command(self, arguments, stdin=None, check=True, sensitive=False):
        result = subprocess.run(
            arguments,
            input=stdin,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "command": arguments,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

        if not sensitive:
            with (ROOT / "logs/commands.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

        if check and result.returncode:
            raise RuntimeError(f"Command failed: {arguments}\n{result.stderr}")

        return result

    def kubectl(self, *arguments, namespace=NAMESPACE, **options):
        command = ["kubectl", "--context", "docker-desktop"]

        if namespace:
            command += ["-n", namespace]

        return self.command(command + list(arguments), **options)

    def inspect(self, kind, name=None, namespace=NAMESPACE):
        arguments = ["get", kind]

        if name:
            arguments.append(name)

        return json.loads(self.kubectl(*arguments, "-o", "json", namespace=namespace).stdout)

    def apply(self, name, documents):
        values = documents if isinstance(documents, list) else [documents]
        text = yaml.safe_dump_all(values, allow_unicode=True, sort_keys=False)
        (ROOT / "manifests" / f"{name}.yaml").write_text(text, encoding="utf-8")
        self.kubectl("apply", "-f", "-", stdin=text, namespace=None)

    def persist(self):
        if self.summary_path.exists():
            previous = json.loads(self.summary_path.read_text(encoding="utf-8"))
            self.summary = previous | self.summary

        save_json(self.summary_path, self.summary)

    def wait(self, predicate, timeout=180):
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            result = predicate()

            if result:
                return result

            time.sleep(2)

        raise TimeoutError("Kubernetes state did not reach the expected value")

    def snapshot(self, label, namespace=NAMESPACE):
        for kind in ("pods", "jobs", "events"):
            value = self.inspect(kind, namespace=namespace)
            save_json(ROOT / "evidence" / f"{label}-{kind}.json", value)

        result = self.kubectl("describe", "pods", namespace=namespace)
        text = "\n".join(line.rstrip() for line in result.stdout.splitlines()) + "\n"
        (ROOT / "logs" / f"{label}-describe.txt").write_text(text, encoding="utf-8")

    def storage(self, endpoint):
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=self.credentials["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=self.credentials["AWS_SECRET_ACCESS_KEY"],
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def prepare(self):
        namespace = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE}}
        self.apply("namespace", namespace)
        secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "s3-credentials", "namespace": NAMESPACE},
            "type": "Opaque",
            "stringData": self.credentials,
        }
        self.kubectl("apply", "-f", "-", stdin=json.dumps(secret), sensitive=True)
        result = self.command(
            ["docker", "build", "-f", str(ROOT / "Dockerfile"), "-t", IMAGE, str(ROOT.parent)]
        )
        (ROOT / "logs/build.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
        node = self.inspect("nodes", namespace=None)["items"][0]
        self.summary["node"] = {
            "name": node["metadata"]["name"],
            "version": node["status"]["nodeInfo"]["kubeletVersion"],
            "allocatable": node["status"]["allocatable"],
        }
        self.summary["image"] = json.loads(
            self.command(["docker", "image", "inspect", IMAGE, "--format", "{{json .Id}}"]).stdout
        )
        self.persist()

    @contextmanager
    def forwarded_storage(self):
        output = (ROOT / "logs/s3-port-forward.txt").open("a", encoding="utf-8")
        process = subprocess.Popen(
            [
                "kubectl",
                "--context",
                "docker-desktop",
                "-n",
                NAMESPACE,
                "port-forward",
                "service/s3",
                "19000:9000",
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        client = self.storage("http://127.0.0.1:19000")

        def ready():
            try:
                client.list_buckets()
                return True
            except Exception:
                return False

        try:
            self.wait(ready)
            yield client
        finally:
            process.terminate()
            process.wait(timeout=15)
            output.close()
