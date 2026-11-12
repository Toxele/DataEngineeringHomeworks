import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kazoo.exceptions import BadVersionError

from .events import EventLog
from .publication import PublicationStore


class ResultServer(ThreadingHTTPServer):
    def __init__(self):
        self.store = PublicationStore(Path("/state/publications.sqlite"))
        self.events = EventLog("receiver")
        super().__init__(("0.0.0.0", 9180), ResultHandler)


class ResultHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def respond(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parts = self.path.strip("/").split("/")

        if len(parts) != 3 or parts[0] != "runs":
            self.respond(404, {"error": "NotFound"})
            return

        _, scenario, operation = parts
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))

        try:
            if operation == "create":
                result = self.server.store.create_run(scenario, payload["fencing"])
            elif operation == "claim":
                result = self.server.store.claim(scenario, payload["epoch"])
            elif operation == "publish":
                result = self.server.store.publish(scenario, payload)
            else:
                self.respond(404, {"error": "NotFound"})
                return

            self.server.events.write(
                operation,
                scenario=scenario,
                payload=payload,
                pointer_version=result["pointer_version"],
            )
            self.respond(200, result)
        except BadVersionError as error:
            self.server.events.write(
                "rejected",
                scenario=scenario,
                error="BadVersionError",
                payload=payload,
                message=str(error),
            )
            self.respond(409, {"error": "BadVersionError", "message": str(error)})

    def do_GET(self):
        if self.path.startswith("/runs/"):
            result = self.server.store.inspect(self.path.rsplit("/", 1)[-1])
            self.respond(200 if result else 404, result or {"error": "NotFound"})
            return

        if self.path == "/health":
            self.respond(200, {"status": "ready"})
            return

        evidence = Path("/evidence/summary.json")
        data = json.loads(evidence.read_text(encoding="utf-8")) if evidence.exists() else {}
        view = "quorum" if self.path == "/quorum" else "failover"
        sections = []

        if view == "quorum":
            sections.append("<h2>Проверка серверов и сессии</h2>")

            titles = {
                "three_servers": "Все серверы работают",
                "one_server_stopped": "Один сервер остановлен",
                "two_servers_stopped": "Два сервера остановлены",
                "ensemble_restored": "Серверы запущены снова",
                "ephemeral_session_closed": "Сессия закрыта",
            }

            for item in data.get("quorum", []):
                title = html.escape(titles.get(item["stage"], item["stage"]))
                snapshot = dict(item)

                if "roles" in snapshot:
                    snapshot["roles"] = {
                        name: next(
                            (line for line in value.splitlines() if line.startswith("Mode:")),
                            value,
                        )
                        for name, value in snapshot["roles"].items()
                    }

                value = html.escape(json.dumps(snapshot, ensure_ascii=False, indent=2))
                sections.append(f"<section><h3>{title}</h3><pre>{value}</pre></section>")
        else:
            sections.append("<h2>Смена лидера</h2>")

            for name, title in (("unfenced", "Без защиты"), ("fenced", "С защитой")):
                experiment = data.get("scenarios", {}).get(name, {})
                result = self.server.store.inspect(experiment.get("scenario", name))
                if result:
                    value = {
                        "FENCING": experiment.get("FENCING"),
                        "old_leader": experiment.get("old_leader"),
                        "backup": experiment.get("backup"),
                        "failover_s": experiment.get("failover_s"),
                        "pause_s": experiment.get("pause_s"),
                        "resumed_from_rows": experiment.get("resumed_from_rows"),
                        "receiver_epoch": result["epoch"],
                        "pointer_version": result["pointer_version"],
                        "pointer_coordinator": result["pointer"]["coordinator"]
                        if result["pointer"]
                        else None,
                        "stale_error": experiment.get("stale_error"),
                        "publications": [
                            {
                                key: publication[key]
                                for key in ("coordinator", "epoch", "keys", "occurrences", "sha256")
                            }
                            for publication in result["publications"]
                        ],
                        "all_frequencies_equal_hw3": all(
                            row["all_frequencies_equal_hw3"]
                            for row in experiment.get("comparisons", [])
                        ),
                    }
                    sections.append(
                        "<section><h3>"
                        + title
                        + "</h3><pre>"
                        + html.escape(json.dumps(value, ensure_ascii=False, indent=2))
                        + "</pre></section>"
                    )

        body = (
            """<!doctype html><html lang="ru"><meta charset="utf-8">
            <title>Результаты</title>
            <style>body{font:16px Arial;margin:30px auto;max-width:1400px;background:#f1f4f8;color:#172235}
            h1{font-size:26px}nav{margin:20px 0}a{color:#1757b7;margin-right:24px}
            main{display:grid;grid-template-columns:1fr 1fr;gap:18px}h2{grid-column:1/-1}
            section{background:white;padding:16px;border:1px solid #c9d2df;border-radius:6px}
            pre{font:13px Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
            h3{margin-top:0}</style><h1>Результаты</h1>
            <nav><a href="/quorum">Серверы и сессия</a>
            <a href="/">Смена лидера</a></nav><main>"""
            + "".join(sections)
            + "</main></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ResultServer().serve_forever()
