"""
Local evidence storage for the dev/laptop stand.

This is NOT a substitute for S3 Object Lock / real WORM storage — it is a
local approximation so the golden-path pipeline is fully testable offline:
  - each evidence package and its video segment are written once, then
    chmod'd read-only (best-effort on POSIX; Windows will just skip this)
  - a hash-chained ledger file (ledger.jsonl) records every write, so any
    out-of-band edit or reordering of files is detectable by replaying the
    chain and recomputing hashes
Swap this module out for a real S3 Object Lock client before field use.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .merkle import sha256_hex


@dataclass
class LedgerEntry:
    seq: int
    kind: str          # "evidence" | "batch_commitment"
    ref_id: str         # event_id or batch_id
    content_hash: str
    prev_hash: str
    entry_hash: str
    timestamp: str


class WormStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.evidence_dir = data_dir / "evidence"
        self.segments_dir = data_dir / "segments"
        self.batches_dir = data_dir / "batches"
        self.ledger_path = data_dir / "ledger.jsonl"
        for d in (self.evidence_dir, self.segments_dir, self.batches_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._seq = self._load_last_seq()

    # -- ledger -------------------------------------------------------

    def _load_last_seq(self) -> int:
        if not self.ledger_path.exists():
            return 0
        last = 0
        with self.ledger_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)["seq"]
        return last

    def _last_entry_hash(self) -> str:
        if not self.ledger_path.exists():
            return "0" * 64
        last_hash = "0" * 64
        with self.ledger_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last_hash = json.loads(line)["entry_hash"]
        return last_hash

    def _append_ledger(self, kind: str, ref_id: str, content_hash: str) -> LedgerEntry:
        self._seq += 1
        prev_hash = self._last_entry_hash()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        entry_hash = sha256_hex(
            f"{self._seq}|{kind}|{ref_id}|{content_hash}|{prev_hash}|{timestamp}".encode("utf-8")
        )
        entry = LedgerEntry(
            seq=self._seq, kind=kind, ref_id=ref_id, content_hash=content_hash,
            prev_hash=prev_hash, entry_hash=entry_hash, timestamp=timestamp,
        )
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.__dict__) + "\n")
        return entry

    def verify_ledger(self) -> bool:
        """Replay the ledger and confirm the hash chain is unbroken."""
        if not self.ledger_path.exists():
            return True
        prev_hash = "0" * 64
        with self.ledger_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                e = json.loads(line)
                expected = sha256_hex(
                    f"{e['seq']}|{e['kind']}|{e['ref_id']}|{e['content_hash']}|{prev_hash}|{e['timestamp']}".encode("utf-8")
                )
                if expected != e["entry_hash"]:
                    return False
                prev_hash = e["entry_hash"]
        return True

    # -- writes ---------------------------------------------------------

    def _write_once(self, path: Path, data: bytes) -> None:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing WORM object: {path}")
        path.write_bytes(data)
        try:
            path.chmod(0o444)
        except OSError:
            pass

    def store_evidence(self, event_id: str, package_dict: Dict[str, Any], video_bytes: bytes) -> None:
        seg_path = self.segments_dir / f"{event_id}.bin"
        self._write_once(seg_path, video_bytes)

        pkg_path = self.evidence_dir / f"{event_id}.json"
        pkg_bytes = json.dumps(package_dict, sort_keys=True, indent=2).encode("utf-8")
        self._write_once(pkg_path, pkg_bytes)

        self._append_ledger("evidence", event_id, sha256_hex(pkg_bytes))

    def store_batch_commitment(self, batch_id: str, commitment: Dict[str, Any]) -> None:
        path = self.batches_dir / f"{batch_id}.json"
        data = json.dumps(commitment, sort_keys=True, indent=2).encode("utf-8")
        self._write_once(path, data)
        self._append_ledger("batch_commitment", batch_id, sha256_hex(data))
