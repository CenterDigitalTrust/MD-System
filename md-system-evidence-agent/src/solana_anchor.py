"""
Anchors a Merkle root to Solana Devnet using the public Memo program —
no custom on-chain program needed for the golden-path pilot. Only the
commitment (batch_id, merkle_root, hash_algo, timestamp) is written
on-chain; never raw evidence or personal data.

The Evidence Signer keypair here is intentionally separate from any
mint authority / treasury key (see pilot guide section 14) — it should
only ever be able to submit memo transactions, nothing else.

If Solana is disabled in config, or the network/keypair isn't available,
commitments are appended to a local pending queue instead of raising —
this mirrors the STEALTH/offline -> SYNC/online behaviour of the field
devices themselves. Call `flush_pending()` once connectivity is back.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class AnchorResult:
    status: str  # "finalized" | "queued" | "error"
    signature: Optional[str] = None
    slot: Optional[int] = None
    detail: Optional[str] = None


class SolanaAnchor:
    MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"

    def __init__(
        self,
        enabled: bool,
        rpc_url: str,
        keypair_path: Path,
        pending_queue_path: Path,
    ):
        self.enabled = enabled
        self.rpc_url = rpc_url
        self.keypair_path = keypair_path
        self.pending_queue_path = pending_queue_path
        self.pending_queue_path.parent.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._keypair = None
        if self.enabled:
            self._try_init_client()

    def _try_init_client(self) -> None:
        try:
            # Imported lazily so the rest of the agent works even if
            # solana/solders aren't installed (e.g. Solana disabled in config).
            from solders.keypair import Keypair  # type: ignore
            from solana.rpc.api import Client  # type: ignore

            if not self.keypair_path.exists():
                raise FileNotFoundError(
                    f"no devnet keypair at {self.keypair_path}. "
                    f"Generate one with: solana-keygen new -o {self.keypair_path}"
                )
            raw = json.loads(self.keypair_path.read_text())
            self._keypair = Keypair.from_bytes(bytes(raw))
            self._client = Client(self.rpc_url)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully, log via caller
            self.enabled = False
            self._init_error = str(exc)

    def _queue(self, commitment: Dict[str, Any], reason: str) -> AnchorResult:
        entry = {**commitment, "queued_at": time.time(), "reason": reason}
        with self.pending_queue_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return AnchorResult(status="queued", detail=reason)

    def anchor(self, commitment: Dict[str, Any]) -> AnchorResult:
        """
        commitment must contain at least: batch_id, merkle_root, hash_algo,
        created_at. Keep the memo payload small and non-sensitive.
        """
        if not self.enabled or self._client is None or self._keypair is None:
            reason = getattr(self, "_init_error", "solana anchoring disabled in config")
            return self._queue(commitment, reason)

        try:
            from solders.instruction import AccountMeta, Instruction  # type: ignore
            from solders.pubkey import Pubkey  # type: ignore
            from solders.transaction import Transaction  # type: ignore
            from solders.message import Message  # type: ignore

            memo_payload = json.dumps(
                {
                    "b": commitment["batch_id"],
                    "r": commitment["merkle_root"],
                    "h": commitment.get("hash_algo", "sha256"),
                    "t": commitment["created_at"],
                },
                separators=(",", ":"),
            ).encode("utf-8")

            program_id = Pubkey.from_string(self.MEMO_PROGRAM_ID)
            ix = Instruction(
                program_id=program_id,
                accounts=[AccountMeta(pubkey=self._keypair.pubkey(), is_signer=True, is_writable=True)],
                data=memo_payload,
            )
            latest_blockhash = self._client.get_latest_blockhash().value.blockhash
            msg = Message.new_with_blockhash([ix], self._keypair.pubkey(), latest_blockhash)
            tx = Transaction([self._keypair], msg, latest_blockhash)

            resp = self._client.send_transaction(tx)
            sig = str(resp.value)
            return AnchorResult(status="finalized", signature=sig)
        except Exception as exc:  # noqa: BLE001
            return self._queue(commitment, f"send_transaction failed: {exc}")

    def flush_pending(self) -> int:
        """Retry everything in the pending queue. Returns count still pending afterwards."""
        if not self.pending_queue_path.exists():
            return 0
        lines = [l for l in self.pending_queue_path.read_text().splitlines() if l.strip()]
        still_pending = []
        for line in lines:
            entry = json.loads(line)
            entry.pop("queued_at", None)
            entry.pop("reason", None)
            result = self.anchor(entry)
            if result.status != "finalized":
                still_pending.append(line)
        self.pending_queue_path.write_text("\n".join(still_pending) + ("\n" if still_pending else ""))
        return len(still_pending)
