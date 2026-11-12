import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class EventLog:
    def __init__(self, name: str):
        self.path = Path("/logs") / f"{name}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def write(self, event: str, **values):
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "time_ns": time.time_ns(),
            "event": event,
            **values,
        }
        line = json.dumps(record, ensure_ascii=False)

        with self.lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

            print(line, flush=True)

        return record
