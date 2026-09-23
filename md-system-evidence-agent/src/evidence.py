"""
Evidence package construction and device-key signing.

Field names follow the "Minimal evidence package" table from the MD System
pilot guide (section 13): event_id, device_id, video_segment_hash,
metadata_hash, model_version/hash, firmware_version/hash, confidence,
event_type, pre/post buffer, quality_metrics, device_signature.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization

from .merkle import sha256_hex


# --------------------------------------------------------------------------
# Device signing key
# --------------------------------------------------------------------------

class DeviceSigner:
    """
    Represents the device's own signing key (distinct from the Evidence
    Signer keypair used to sign Merkle roots). Ed25519, generated once per
    device and persisted to disk so the device_id <-> key binding is stable.
    """

    def __init__(self, private_key: Ed25519PrivateKey):
        self._key = private_key

    @classmethod
    def load_or_create(cls, key_path: Path) -> "DeviceSigner":
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            raw = key_path.read_bytes()
            key = Ed25519PrivateKey.from_private_bytes(raw)
        else:
            key = Ed25519PrivateKey.generate()
            raw = key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
            key_path.write_bytes(raw)
            try:
                key_path.chmod(0o400)
            except OSError:
                pass  # best-effort on platforms without POSIX perms
        return cls(key)

    def public_hex(self) -> str:
        pub: Ed25519PublicKey = self._key.public_key()
        raw = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return raw.hex()

    def sign(self, data: bytes) -> str:
        return self._key.sign(data).hex()


# --------------------------------------------------------------------------
# Evidence package
# --------------------------------------------------------------------------

@dataclass
class QualityMetrics:
    sharpness: float
    brightness: float
    dropped_frames: int


@dataclass
class EvidencePackage:
    event_id: str
    device_id: str
    video_segment_hash: str
    metadata_hash: str
    model_version: str
    model_hash: str
    firmware_version: str
    firmware_hash: str
    confidence: float
    event_type: str
    pre_event_buffer_s: float
    post_event_buffer_s: float
    quality_metrics: QualityMetrics
    created_at: str
    device_signature: Optional[str] = None
    # NOTE: left null here on purpose. This object is written to WORM storage
    # at capture time, before batching happens, and WORM objects are never
    # rewritten — so batch_id/merkle_proof for this event live in the batch
    # commitment record instead (see WormStore.store_batch_commitment /
    # EdgeAgent._close_batch's `members` map), not on this sealed copy.
    batch_id: Optional[str] = None
    merkle_proof: Optional[list] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def canonical_bytes(self) -> bytes:
        """
        Deterministic byte representation used both as the Merkle leaf input
        and as what device_signature actually signs. Excludes fields that are
        only known after batching (batch_id, merkle_proof, device_signature
        itself) so the signature covers the package as captured on-device.
        """
        d = self.to_dict()
        d.pop("device_signature", None)
        d.pop("batch_id", None)
        d.pop("merkle_proof", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def leaf_hash(self) -> str:
        return sha256_hex(self.canonical_bytes())


def build_evidence_package(
    *,
    device_id: str,
    video_bytes: bytes,
    event_type: str,
    confidence: float,
    model_version: str,
    model_hash: str,
    firmware_version: str,
    firmware_hash: str,
    quality_metrics: QualityMetrics,
    pre_event_buffer_s: float,
    post_event_buffer_s: float,
    signer: DeviceSigner,
    metadata_extra: Optional[Dict[str, Any]] = None,
) -> EvidencePackage:
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    video_segment_hash = sha256_hex(video_bytes)
    metadata_payload = {
        "event_id": event_id,
        "device_id": device_id,
        "event_type": event_type,
        "created_at": created_at,
        **(metadata_extra or {}),
    }
    metadata_hash = sha256_hex(
        json.dumps(metadata_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )

    pkg = EvidencePackage(
        event_id=event_id,
        device_id=device_id,
        video_segment_hash=video_segment_hash,
        metadata_hash=metadata_hash,
        model_version=model_version,
        model_hash=model_hash,
        firmware_version=firmware_version,
        firmware_hash=firmware_hash,
        confidence=confidence,
        event_type=event_type,
        pre_event_buffer_s=pre_event_buffer_s,
        post_event_buffer_s=post_event_buffer_s,
        quality_metrics=quality_metrics,
        created_at=created_at,
    )
    pkg.device_signature = signer.sign(pkg.canonical_bytes())
    return pkg
