"""
Minimal audit log for "who opened what, when, and why" — a stripped-down
stand-in for the full КЕП/role/purpose/scope access layer described in the
pilot guide (section 15). Good enough for the golden-path stand to prove
the concept; production needs real identity (КЕП), role/purpose/scope
checks enforced *before* granting access, not just logged after the fact.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .merkle import sha256_hex


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = "0" * 64
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)["entry_hash"]
        return last

    def log(
        self,
        actor: str,
        role: str,
        purpose: str,
        action: str,
        ref_id: str,
        scope: Optional[str] = None,
    ) -> None:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        prev_hash = self._last_hash()
        body = {
            "actor": actor, "role": role, "purpose": purpose,
            "action": action, "ref_id": ref_id, "scope": scope,
            "timestamp": timestamp, "prev_hash": prev_hash,
        }
        entry_hash = sha256_hex(json.dumps(body, sort_keys=True).encode("utf-8"))
        body["entry_hash"] = entry_hash
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body) + "\n")
