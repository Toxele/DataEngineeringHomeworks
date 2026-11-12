import csv
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from kazoo.client import KazooClient
from kazoo.retry import KazooRetry

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
LOGS = ROOT / "logs"
HOSTS = "127.0.0.1:2181,127.0.0.1:2182,127.0.0.1:2183"


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_events(path: Path):
    if not path.exists():
        return []

    events = []

    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return events


class Laboratory:
    def __init__(self):
        EVIDENCE.mkdir(exist_ok=True)
        LOGS.mkdir(exist_ok=True)
        self.summary_path = EVIDENCE / "summary.json"
        self.summary = (
            json.loads(self.summary_path.read_text(encoding="utf-8"))
            if self.summary_path.exists()
            else {
                "date": datetime.now(timezone.utc).isoformat(),
                "quorum": [],
                "scenarios": {},
            }
        )
        self.environment = os.environ.copy()

    def command(self, arguments: list[str], check=True, stdin=None):
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            env=self.environment,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        record = {
            "command": arguments,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

        with (LOGS / "commands.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

        if check and result.returncode:
            raise RuntimeError(f"Command failed: {arguments}\n{result.stderr}")

        return result

    def compose(self, *arguments, check=True):
        return self.command(["docker", "compose", *arguments], check=check)

    def persist(self):
        save_json(self.summary_path, self.summary)

    def wait(self, predicate, timeout=60):
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            result = predicate()

            if result:
                return result

            time.sleep(0.2)

        raise TimeoutError("Experiment condition was not reached")

    def api(self, path, payload=None):
        request = Request(
            "http://127.0.0.1:9180" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )

        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def prepare(self):
        for node in (1, 2, 3):
            for name in ("data", "datalog"):
                (ROOT / "state" / f"zk{node}" / name).mkdir(parents=True, exist_ok=True)

        inspection = subprocess.run(
            ["docker", "inspect", "rustfs-lab"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        details = json.loads(inspection.stdout)[0]
        credentials = dict(item.split("=", 1) for item in details["Config"]["Env"] if "=" in item)
        (ROOT / ".env").write_text(
            "S3_ENDPOINT=http://rustfs-lab:9000\n"
            + f"AWS_ACCESS_KEY_ID={credentials['RUSTFS_ACCESS_KEY']}\n"
            + f"AWS_SECRET_ACCESS_KEY={credentials['RUSTFS_SECRET_KEY']}\n",
            encoding="utf-8",
        )
        self.command(["docker", "start", "rustfs-lab"])
        self.compose("build", "receiver")
        self.compose("up", "-d", "zk1", "zk2", "zk3", "receiver")
        networks = details.get("NetworkSettings", {}).get("Networks", {})

        if "apache-zookeeper-lab" not in networks:
            self.command(["docker", "network", "connect", "apache-zookeeper-lab", "rustfs-lab"])

        self.wait(lambda: self.roles_ready(), timeout=90)
        self.wait(lambda: self.receiver_ready(), timeout=30)
        image = self.command(
            ["docker", "image", "inspect", "zookeeper:3.9.6", "--format", "{{json .RepoDigests}}"]
        ).stdout.strip()
        self.summary["environment"] = {
            "zookeeper": "3.9.6",
            "image_digest": json.loads(image),
            "session_timeout_s": 10,
            "branch": "apache-zookeeper",
        }
        self.persist()

    def receiver_ready(self):
        try:
            return self.api("/health")["status"] == "ready"
        except OSError:
            return False

    def roles(self):
        roles = {}

        for node in (1, 2, 3):
            try:
                with socket.create_connection(("127.0.0.1", 2180 + node), timeout=2) as connection:
                    connection.settimeout(2)
                    connection.sendall(b"srvr")
                    response = connection.recv(8192).decode(errors="replace")
                    roles[f"zk{node}"] = response.strip()
            except OSError as error:
                roles[f"zk{node}"] = type(error).__name__

        return roles

    def roles_ready(self):
        roles = self.roles()
        return (
            roles
            if sum("Mode: leader" in value for value in roles.values()) == 1
            and sum("Mode: follower" in value for value in roles.values()) == 2
            else None
        )

    def probe(self):
        retry = KazooRetry(max_tries=1, delay=0.1)
        client = KazooClient(hosts=HOSTS, timeout=4, connection_retry=retry, command_retry=retry)

        try:
            client.start(timeout=4)
            path = "/homework4/probe-" + uuid.uuid4().hex
            client.create_async(path, b"quorum-write", makepath=True).get(timeout=5)
            value, _ = client.get_async(path).get(timeout=5)
            client.delete_async(path).get(timeout=5)

            return {"write_ok": value == b"quorum-write"}
        except Exception as error:
            return {"write_ok": False, "error": type(error).__name__, "message": str(error)}
        finally:
            client.stop()
            client.close()

    def infrastructure(self):
        roles = self.wait(self.roles_ready)
        self.summary["quorum"] = [{"stage": "three_servers", "roles": roles, **self.probe()}]
        assert self.summary["quorum"][-1]["write_ok"]
        followers = [name for name, role in roles.items() if "Mode: follower" in role]
        self.compose("stop", followers[0])
        time.sleep(3)
        self.summary["quorum"].append(
            {
                "stage": "one_server_stopped",
                "stopped": followers[:1],
                "roles": self.roles(),
                **self.probe(),
            }
        )
        assert self.summary["quorum"][-1]["write_ok"]
        self.compose("stop", followers[1])
        time.sleep(3)
        self.summary["quorum"].append(
            {
                "stage": "two_servers_stopped",
                "stopped": followers,
                "roles": self.roles(),
                **self.probe(),
            }
        )
        assert not self.summary["quorum"][-1]["write_ok"]
        self.compose("start", *followers)
        self.wait(self.roles_ready)
        self.summary["quorum"].append(
            {"stage": "ensemble_restored", "roles": self.roles(), **self.probe()}
        )
        self.ephemeral()

        for node in (1, 2, 3):
            result = self.compose(
                "exec",
                "-T",
                f"zk{node}",
                "sh",
                "-c",
                'cat /conf/zoo.cfg; printf "\\nmyid="; cat /data/myid',
            )
            (EVIDENCE / f"zk{node}-configuration.txt").write_text(result.stdout, encoding="utf-8")

        self.persist()
        print(
            "Infrastructure: quorum, loss of one/two servers and ephemeral session verified.",
            flush=True,
        )

    def ephemeral(self):
        client = KazooClient(hosts=HOSTS, timeout=10)
        client.start()
        client.ensure_path("/homework4")
        node = "/homework4/ephemeral-demo-" + uuid.uuid4().hex[:8]
        log_path = LOGS / "zkcli-ephemeral.txt"

        with log_path.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                ["docker", "compose", "exec", "-T", "zk1", "zkCli.sh", "-server", "zk2:2181"],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
            process.stdin.write(f"create -e {node} alive\nget -s {node}\n")
            process.stdin.flush()
            stat = self.wait(lambda: client.exists(node), timeout=30)
            owner = stat.ephemeralOwner
            process.stdin.write("quit\n")
            process.stdin.flush()
            process.communicate(timeout=20)

        self.wait(lambda: client.exists(node) is None, timeout=20)
        self.summary["quorum"].append(
            {
                "stage": "ephemeral_session_closed",
                "path": node,
                "owner_session_hex": hex(owner),
                "existed_during_session": bool(owner),
                "exists_after_quit": client.exists(node) is not None,
                "zkcli_exit_code": process.returncode,
            }
        )
        client.stop()
        client.close()

    def events(self, scenario, identifier):
        return read_events(LOGS / f"{scenario}-{identifier}.jsonl")

    def find_event(self, scenario, identifier, event):
        return next(
            (item for item in self.events(scenario, identifier) if item["event"] == event), None
        )

    def scenario(self, fencing: bool):
        label = "fenced" if fencing else "unfenced"
        scenario = label + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self.environment["SCENARIO"] = scenario
        self.environment["FENCING"] = str(int(fencing))
        self.api(f"/runs/{scenario}/create", {"fencing": fencing})
        client = KazooClient(hosts=HOSTS, timeout=10)
        client.start()
        client.ensure_path(f"/homework4/{scenario}")
        client.create(f"/homework4/{scenario}/epoch", b"0")
        client.create(f"/homework4/{scenario}/checkpoint", b"")
        client.stop()
        client.close()
        self.compose("up", "-d", "--force-recreate", "coordinator-a", "coordinator-b")
        leader = self.wait(
            lambda: next(
                (name for name in ("a", "b") if self.find_event(scenario, name, "leader_acquired")),
                None,
            )
        )
        backup = "b" if leader == "a" else "a"
        checkpoint = self.wait(lambda: self.find_event(scenario, leader, "checkpoint_saved"))
        self.wait(lambda: self.find_event(scenario, backup, "candidate_registered"))
        pause_requested = time.time_ns()
        self.compose("pause", f"coordinator-{leader}")
        pause_completed = time.time_ns()
        acquisition = self.wait(
            lambda: self.find_event(scenario, backup, "leader_acquired"), timeout=45
        )
        self.wait(lambda: self.find_event(scenario, backup, "result_published"), timeout=70)
        remaining = 40 - (time.time_ns() - pause_completed) / 1e9

        if remaining > 0:
            time.sleep(remaining)

        resume_requested = time.time_ns()
        self.compose("unpause", f"coordinator-{leader}")
        self.wait(lambda: self.find_event(scenario, leader, "coordinator_finished"), timeout=80)
        state = self.api(f"/runs/{scenario}")
        loaded = self.find_event(scenario, backup, "checkpoint_loaded")
        rejected = self.find_event(scenario, leader, "publication_rejected")
        expected_writes = 1 if fencing else 2
        assert len(state["publications"]) == expected_writes
        assert state["pointer_version"] == expected_writes
        assert state["pointer"]["coordinator"] == (backup if fencing else leader)
        assert bool(rejected) == fencing
        assert 0 < loaded["rows"] < 229388
        comparisons = self.verify_results(scenario)
        record = {
            "scenario": scenario,
            "FENCING": int(fencing),
            "old_leader": leader,
            "backup": backup,
            "pause_requested_ns": pause_requested,
            "pause_completed_ns": pause_completed,
            "new_leader_ns": acquisition["time_ns"],
            "resume_requested_ns": resume_requested,
            "failover_s": (acquisition["time_ns"] - pause_completed) / 1e9,
            "pause_s": (resume_requested - pause_completed) / 1e9,
            "old_checkpoint_rows": checkpoint["rows"],
            "resumed_from_rows": loaded["rows"],
            "new_epoch": acquisition["epoch"],
            "accepted_publications": len(state["publications"]),
            "pointer_version": state["pointer_version"],
            "pointer_coordinator": state["pointer"]["coordinator"],
            "stale_error": rejected["error"] if rejected else None,
            "comparisons": comparisons,
        }
        self.summary["scenarios"][label] = record
        save_json(EVIDENCE / f"{label}-receiver.json", state)
        self.persist()
        self.compose("logs", "--no-color", "--timestamps", "coordinator-a", "coordinator-b")
        print(json.dumps(record, ensure_ascii=False), flush=True)

    def verify_results(self, scenario):
        reference = ROOT.parent / "hw-3/artifacts/mr_combiner_1/skills_2.csv"
        counts = self.read_counts(reference)
        comparisons = []

        for identifier in ("a", "b"):
            path = ROOT / "state/results" / f"{scenario}-{identifier}.csv"
            actual = self.read_counts(path)
            assert actual == counts, f"Frequency mismatch: {path}"

            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()

            comparisons.append(
                {
                    "coordinator": identifier,
                    "keys": len(actual),
                    "occurrences": sum(actual.values()),
                    "sha256": digest,
                    "all_frequencies_equal_hw3": True,
                }
            )

        return comparisons

    @staticmethod
    def read_counts(path):
        with path.open(encoding="utf-8", newline="") as stream:
            return {
                (row["skill_1"], row["skill_2"]): int(row["frequency"])
                for row in csv.DictReader(stream)
            }

    def experiments(self):
        try:
            self.scenario(False)
            self.scenario(True)
        finally:
            self.compose("unpause", "coordinator-a", "coordinator-b", check=False)
        result = self.compose("logs", "--no-color", "--timestamps", "zk1", "zk2", "zk3", "receiver")
        (LOGS / "ensemble-and-receiver.txt").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )
        self.command(["docker", "compose", "ps", "-a"])


def main():
    laboratory = Laboratory()
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"

    if stage in ("prepare", "all"):
        laboratory.prepare()

    if stage in ("infrastructure", "all"):
        laboratory.infrastructure()

    if stage in ("experiments", "all"):
        laboratory.experiments()


if __name__ == "__main__":
    main()
