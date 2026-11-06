"""Append-only, hash-chained audit ledger.

Each entry's SHA-256 covers its own content plus the previous entry's hash, so
editing or deleting any historical entry breaks verification of the chain.
"""
import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Dict, List

from .models import AuditLog

GENESIS = "0" * 64


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(prev_hash: str, entry_id: str, ts: str, actor: str, action: str, entity_id: str, details: Dict) -> str:
    payload = json.dumps(
        {"prev": prev_hash, "id": entry_id, "ts": ts, "actor": actor, "action": action,
         "entity": entity_id, "details": details},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class AuditLedger:
    def __init__(self) -> None:
        self._entries: List[AuditLog] = []
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._entries = []

    def record(self, actor: str, action: str, entity_id: str, details: Dict) -> AuditLog:
        with self._lock:
            prev = self._entries[-1].sha256_proof if self._entries else GENESIS
            entry_id = f"AUD-{len(self._entries) + 1001}"
            ts = utcnow()
            digest = _digest(prev, entry_id, ts, actor, action, entity_id, details)
            entry = AuditLog(id=entry_id, timestamp=ts, actor=actor, action=action, entity_id=entity_id,
                             details=details, prev_hash=prev, sha256_proof=digest)
            self._entries.append(entry)
            return entry

    def dump(self) -> List[Dict]:
        return [e.model_dump() for e in self._entries]

    def load(self, entries: List[Dict]) -> None:
        with self._lock:
            self._entries = [AuditLog(**e) for e in entries]

    def latest(self, limit: int = 50) -> List[Dict]:
        return [e.model_dump() for e in reversed(self._entries[-limit:])]

    def all(self) -> List[AuditLog]:
        return list(self._entries)

    def verify(self) -> Dict:
        prev = GENESIS
        for e in self._entries:
            expected = _digest(prev, e.id, e.timestamp, e.actor, e.action, e.entity_id, e.details)
            if e.prev_hash != prev or e.sha256_proof != expected:
                return {"valid": False, "broken_at": e.id, "entries": len(self._entries)}
            prev = e.sha256_proof
        return {"valid": True, "broken_at": None, "entries": len(self._entries), "head": prev}
