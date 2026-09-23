"""
Golden-path Edge Evidence Agent.

    camera -> event detection -> evidence package -> Merkle batch
           -> Solana commitment (or offline queue) -> WORM storage

Run against a webcam:      python -m src.agent --source 0
Run against a video file:  python -m src.agent --source sample.mp4
Run against an RTSP cam:   python -m src.agent --source rtsp://192.168.1.50/stream1

This is the M1 "golden path" milestone from the pilot guide (section 9):
one working stand end-to-end, on real hardware or a laptop, before any
money is spent on 10 devices. Nothing here is production-hardened —
see README.md "What this is / is not" before field use.
"""

from __future__ import annotations

import argparse
import signal
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import List

import yaml

from .audit_log import AuditLog
from .capture import FrameSource
from .evidence import DeviceSigner, EvidencePackage, build_evidence_package
from .event_detector import MotionEventDetector, encode_clip
from .merkle import build_batch
from .solana_anchor import SolanaAnchor
from .storage import WormStore


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class EdgeAgent:
    def __init__(self, config: dict, source_override: str | None = None):
        self.cfg = config
        self.device_id = config["device_id"]

        data_dir = Path(config["storage"]["data_dir"])
        self.store = WormStore(data_dir)
        self.audit = AuditLog(data_dir / "audit_log.jsonl")
        self.signer = DeviceSigner.load_or_create(Path(data_dir) / "keys" / "device_key.raw")

        src = source_override if source_override is not None else config["capture"]["source"]
        src = int(src) if isinstance(src, str) and src.isdigit() else src
        self.frame_source = FrameSource(src)

        ed_cfg = config["event_detection"]
        self.detector = MotionEventDetector(
            fps=self.frame_source.fps,
            min_contour_area=ed_cfg["min_contour_area"],
            cooldown_seconds=ed_cfg["cooldown_seconds"],
            pre_buffer_frames=ed_cfg["pre_buffer_frames"],
            post_buffer_frames=ed_cfg["post_buffer_frames"],
        )
        self.post_buffer_frames = ed_cfg["post_buffer_frames"]

        sol_cfg = config["solana"]
        self.anchor = SolanaAnchor(
            enabled=sol_cfg.get("enabled", False),
            rpc_url=sol_cfg.get("rpc_url", "https://api.devnet.solana.com"),
            keypair_path=Path(sol_cfg.get("keypair_path", "./keys/evidence_signer.json")),
            pending_queue_path=data_dir / "pending_commitments.jsonl",
        )

        b_cfg = config["batching"]
        self.batch_size = b_cfg["batch_size"]
        self.batch_timeout_s = b_cfg["batch_timeout_seconds"]

        self._batch: List[EvidencePackage] = []
        self._batch_started_at = time.time()
        self._running = True

    # -- pipeline stages --------------------------------------------------

    def _handle_event(self, det, post_frames) -> None:
        clip_frames = det.clip_frames + post_frames
        det.post_event_buffer_s = round(len(post_frames) / det.fps, 2)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        video_bytes = encode_clip(clip_frames, det.fps, tmp_path)
        Path(tmp_path).unlink(missing_ok=True)

        pkg = build_evidence_package(
            device_id=self.device_id,
            video_bytes=video_bytes,
            event_type=det.event_type,
            confidence=det.confidence,
            model_version=self.cfg["model"]["version"],
            model_hash="n/a-motion-heuristic",  # replace once a real model is wired in
            firmware_version=self.cfg["firmware"]["version"],
            firmware_hash="n/a-dev-build",
            quality_metrics=det.quality_metrics,
            pre_event_buffer_s=det.pre_event_buffer_s,
            post_event_buffer_s=det.post_event_buffer_s,
            signer=self.signer,
        )

        self.store.store_evidence(pkg.event_id, pkg.to_dict(), video_bytes)
        self.audit.log(actor="edge-agent", role="device", purpose="capture", action="store_evidence", ref_id=pkg.event_id)
        print(f"[event] {pkg.event_id} type={pkg.event_type} confidence={pkg.confidence} hash={pkg.video_segment_hash[:16]}…")

        self._batch.append(pkg)
        if len(self._batch) >= self.batch_size or (time.time() - self._batch_started_at) >= self.batch_timeout_s:
            self._close_batch()

    def _close_batch(self) -> None:
        if not self._batch:
            return
        leaves = [pkg.leaf_hash() for pkg in self._batch]
        root, tree = build_batch(leaves)
        batch_id = f"batch_{uuid.uuid4().hex[:10]}"

        # Evidence files are already sealed WORM objects by this point (written
        # at capture time), so we can't retroactively stamp batch_id/merkle_proof
        # into them. Instead the batch commitment carries the event->proof
        # mapping; a verifier joins evidence.json + this file to check a claim.
        members = {}
        for i, pkg in enumerate(self._batch):
            members[pkg.event_id] = {
                "leaf_hash": leaves[i],
                "merkle_proof": [step.__dict__ for step in tree.proof(i)],
            }

        commitment = {
            "batch_id": batch_id,
            "device_id": self.device_id,
            "merkle_root": root,
            "hash_algo": "sha256",
            "event_count": len(self._batch),
            "members": members,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        result = self.anchor.anchor(commitment)
        commitment["anchor_status"] = result.status
        commitment["anchor_signature"] = result.signature
        commitment["anchor_detail"] = result.detail

        self.store.store_batch_commitment(batch_id, commitment)
        self.audit.log(actor="edge-agent", role="device", purpose="batch_close", action="anchor_commitment", ref_id=batch_id)

        print(f"[batch] {batch_id} events={len(self._batch)} root={root[:16]}… status={result.status}"
              + (f" sig={result.signature[:16]}…" if result.signature else ""))

        self._batch = []
        self._batch_started_at = time.time()

    # -- main loop ----------------------------------------------------

    def run(self) -> None:
        print(f"[agent] device_id={self.device_id} source={self.frame_source.source} "
              f"solana_enabled={self.anchor.enabled}")

        def _stop(sig, frame):
            self._running = False
        signal.signal(signal.SIGINT, _stop)

        frame_iter = self.frame_source.frames()
        pending_post: list | None = None
        pending_det = None

        for frame, _ts in frame_iter:
            if not self._running:
                break

            if pending_det is not None:
                pending_post.append(frame)
                if len(pending_post) >= self.post_buffer_frames:
                    self._handle_event(pending_det, pending_post)
                    pending_det, pending_post = None, None
                continue

            det = self.detector.check(frame)
            if det is not None:
                pending_det, pending_post = det, []

        if pending_det is not None and pending_post:
            self._handle_event(pending_det, pending_post)
        self._close_batch()
        self.frame_source.release()
        print(f"[agent] stopped. ledger intact: {self.store.verify_ledger()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MD System golden-path edge agent")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--source", default=None, help="override capture.source: webcam index, file path, or rtsp:// URL")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    agent = EdgeAgent(config, source_override=args.source)
    agent.run()


if __name__ == "__main__":
    sys.exit(main())
