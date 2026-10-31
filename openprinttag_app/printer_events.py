"""Événements PrusaLink éphémères, partagés par les navigateurs abonnés."""
from collections import deque
from copy import deepcopy
import json
import threading
import uuid


def event_frame(kind, value, identifier=None):
    prefix = f"id: {identifier}\n" if identifier is not None else ""
    return prefix + f"event: {kind}\ndata: " + json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n\n"


class PrinterEvents:
    def __init__(self, monitor, interval=5):
        self.monitor, self.interval = monitor, interval
        self.lock = threading.RLock()
        self._subscribers = 0
        self._sequence = 0
        self._session = uuid.uuid4().hex
        self._events = deque(maxlen=64)
        self.reset()

    def reset(self):
        with self.lock:
            self._revision = None
            self._previous = None
            self._job = None
            self._intervention = False
            self._completed = deque(maxlen=64)
            self._events.clear()

    def subscribe(self):
        with self.lock:
            if not self._subscribers:
                self.reset()
            self._subscribers += 1

    def unsubscribe(self):
        with self.lock:
            self._subscribers = max(0, self._subscribers - 1)
            if not self._subscribers:
                self.reset()

    def _append(self, kind, snapshot, job):
        self._sequence += 1
        event = {"id": f"{self._session}:{self._sequence}", "kind": kind,
                 "printer_name": snapshot["name"], "observed_at": snapshot["observed_at"],
                 "job_id": job.get("id"), "filename": job.get("filename"),
                 "state": snapshot["printer"]["state"]}
        if kind == "intervention":
            event["message"] = snapshot["printer"].get("message")
        self._events.append((self._sequence, event))

    def observe(self, snapshot):
        """Un premier état, une panne ou un changement de source ne sont pas des événements."""
        with self.lock:
            revision = snapshot.get("configuration_revision")
            if revision != self._revision or not snapshot.get("connected") or snapshot.get("stale"):
                self.reset()
                self._revision = revision
            if not snapshot.get("connected") or snapshot.get("stale"):
                return
            if snapshot.get("observed_at") == self._previous:
                return
            printer, job = snapshot.get("printer", {}), snapshot.get("job", {})
            state, job_state = printer.get("state"), job.get("state")
            if not state or not job.get("consistent", True):
                return
            # Deux GET peuvent encadrer un changement de travail ou d'état.
            if (job_state == "FINISHED" and state in {"PRINTING", "PAUSED", "ATTENTION", "ERROR", "STOPPED"}
                    or state == "FINISHED" and job_state in {"PRINTING", "PAUSED", "ERROR", "STOPPED"}):
                return
            intervention = state in {"ATTENTION", "ERROR", "PAUSED"}
            current_id = job.get("id") if job.get("id") is not None else job.get("status_id")
            initial = self._previous is None
            self._previous = snapshot.get("observed_at")
            if not initial and intervention and not self._intervention:
                self._append("intervention", snapshot, job if current_id is not None else self._job or {})
            self._intervention = intervention
            finished = state == "FINISHED" or job_state == "FINISHED"
            if (not initial and finished and self._job and state not in {"STOPPED", "ERROR"}
                    and current_id in {None, self._job["id"]} and self._job["id"] not in self._completed):
                self._append("finished", snapshot, self._job)
                self._completed.append(self._job["id"])
            if state == "PRINTING" and current_id is not None:
                self._job = {"id": current_id, "filename": job.get("filename")}
            elif state in {"IDLE", "READY", "BUSY", "FINISHED", "STOPPED", "ERROR"}:
                self._job = None

    def poll(self, after=None):
        with self.lock:
            snapshot = self.monitor.snapshot()
            self.observe(snapshot)
            status = {key: snapshot.get(key) for key in ("configured", "connected", "stale", "observed_at", "message")}
            events = [] if after is None else [deepcopy(event) for sequence, event in self._events if sequence > after]
            return self._sequence, status, events
