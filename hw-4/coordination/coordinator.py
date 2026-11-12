import csv
import hashlib
import json
import os
import time
from collections import Counter
from itertools import combinations, islice
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kazoo.client import KazooClient
from kazoo.exceptions import BadVersionError
from lab.domain import VacancyPolicy
from lab.storage import ObjectStorage

from .events import EventLog


class ResultClient:
    def __init__(self, scenario: str):
        self.url = os.environ.get("RESULT_ENDPOINT", "http://receiver:9180")
        self.scenario = scenario

    def post(self, operation: str, body: dict):
        request = Request(
            f"{self.url}/runs/{self.scenario}/{operation}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )

        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as error:
            result = json.load(error)

            if result.get("error") == "BadVersionError":
                raise BadVersionError(result["message"]) from error

            raise


class CheckpointStore:
    def __init__(self, client: KazooClient, root: str, epoch: int, scenario: str):
        self.client = client
        self.root = root
        self.epoch = epoch
        self.directory = Path("/state/checkpoints") / scenario
        self.directory.mkdir(parents=True, exist_ok=True)

    def load(self):
        payload, _ = self.client.get(self.root + "/checkpoint")

        if not payload:
            return Counter(), 0, 0

        data = json.loads(Path(json.loads(payload)["path"]).read_text(encoding="utf-8"))
        counts = Counter({tuple(key): count for key, count in data["counts"]})

        return counts, data["rows"], data["selected"]

    def save(self, counts: Counter, rows: int, selected: int):
        epoch, epoch_version = self.client.get(self.root + "/epoch")

        if int(epoch) != self.epoch:
            return False

        path = self.directory / f"epoch-{self.epoch}-rows-{rows}.json"
        payload = {"rows": rows, "selected": selected, "counts": list(counts.items())}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        _, version = self.client.get(self.root + "/checkpoint")
        transaction = self.client.transaction()
        transaction.check(self.root + "/epoch", version=epoch_version.version)
        transaction.set_data(
            self.root + "/checkpoint",
            json.dumps({"path": str(path), "rows": rows, "epoch": self.epoch}).encode(),
            version=version.version,
        )
        result = transaction.commit()

        if any(isinstance(item, Exception) for item in result):
            return False

        return True


class PairMapReduce:
    @staticmethod
    def map(rows: list[dict]):
        counts = Counter()
        selected = 0

        for row in rows:
            if VacancyPolicy.matches(row):
                counts.update(combinations(VacancyPolicy.skills(row["key_skills"]), 2))
                selected += 1

        return counts, selected


class Coordinator:
    def __init__(self):
        self.scenario = os.environ["SCENARIO"]
        self.identifier = os.environ["COORDINATOR_ID"]
        self.root = f"/homework4/{self.scenario}"
        self.log = EventLog(f"{self.scenario}-{self.identifier}")
        self.client = KazooClient(
            hosts=os.environ["ZK_HOSTS"], timeout=float(os.environ.get("SESSION_TIMEOUT", "10"))
        )
        self.client.add_listener(self.session_changed)
        self.receiver = ResultClient(self.scenario)

    def session_changed(self, state):
        self.log.write("session_state", state=state)

    def elect(self):
        self.client.start(timeout=30)
        self.client.ensure_path(self.root + "/election")
        candidate = self.client.create(
            self.root + "/election/candidate-",
            self.identifier.encode(),
            ephemeral=True,
            sequence=True,
        )
        self.log.write(
            "candidate_registered", path=candidate, session_timeout_ms=self.client._session_timeout
        )

        while True:
            children = sorted(self.client.get_children(self.root + "/election"))

            if children and candidate.rsplit("/", 1)[-1] == children[0]:
                break

            time.sleep(0.1)

        value, stat = self.client.get(self.root + "/epoch")
        epoch = int(value) + 1
        self.client.set(self.root + "/epoch", str(epoch).encode(), version=stat.version)
        self.receiver.post("claim", {"epoch": epoch})
        self.log.write("leader_acquired", coordinator=self.identifier, epoch=epoch)

        return epoch

    def run(self):
        try:
            epoch = self.elect()
            checkpoints = CheckpointStore(self.client, self.root, epoch, self.scenario)
            counts, rows, selected = checkpoints.load()
            self.log.write("checkpoint_loaded", rows=rows, selected=selected, keys=len(counts))
            source = ObjectStorage().rows()
            source = islice(source, rows, None)
            chunk_size = int(os.environ.get("CHUNK_SIZE", "2000"))
            chunk_number = 0

            while chunk := list(islice(source, chunk_size)):
                partial, selected_chunk = PairMapReduce.map(chunk)
                counts.update(partial)
                rows += len(chunk)
                selected += selected_chunk
                chunk_number += 1

                if chunk_number % 5 == 0:
                    saved = checkpoints.save(counts, rows, selected)
                    self.log.write(
                        "checkpoint_saved" if saved else "checkpoint_skipped",
                        rows=rows,
                        epoch=epoch,
                    )

                time.sleep(float(os.environ.get("CHUNK_DELAY", "0.12")))

            directory = Path("/state/results")
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{self.scenario}-{self.identifier}.csv"

            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["skill_1", "skill_2", "frequency"])
                writer.writerows([*key, count] for key, count in sorted(counts.items()))

            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()

            result = self.receiver.post(
                "publish",
                {
                    "coordinator": self.identifier,
                    "epoch": epoch,
                    "path": str(path),
                    "sha256": digest,
                    "rows": rows,
                    "selected": selected,
                    "keys": len(counts),
                    "occurrences": sum(counts.values()),
                },
            )
            self.log.write(
                "result_published",
                message="записал результат",
                epoch=epoch,
                pointer_version=result["pointer_version"],
                sha256=digest,
            )
        except BadVersionError as error:
            self.log.write("publication_rejected", error="BadVersionError", message=str(error))
        except Exception as error:
            self.log.write("calculation_failed", error=type(error).__name__, message=str(error))
            raise
        finally:
            self.client.stop()
            self.client.close()
            self.log.write("coordinator_finished")


if __name__ == "__main__":
    Coordinator().run()
