"""
Run directly with: python3 tests/test_evidence_storage.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evidence import DeviceSigner, QualityMetrics, build_evidence_package
from src.storage import WormStore
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _make_signer(tmp: Path) -> DeviceSigner:
    return DeviceSigner.load_or_create(tmp / "keys" / "device_key.raw")


def test_signer_key_persists_across_reload():
    tmp = Path(tempfile.mkdtemp())
    try:
        s1 = _make_signer(tmp)
        pub1 = s1.public_hex()
        s2 = _make_signer(tmp)  # should load the same key, not generate a new one
        assert pub1 == s2.public_hex()
    finally:
        shutil.rmtree(tmp)


def test_device_signature_verifies():
    tmp = Path(tempfile.mkdtemp())
    try:
        signer = _make_signer(tmp)
        pkg = build_evidence_package(
            device_id="MD-CAM-TEST",
            video_bytes=b"fake-video-bytes",
            event_type="motion",
            confidence=0.91,
            model_version="test-v0", model_hash="abc",
            firmware_version="test-fw", firmware_hash="def",
            quality_metrics=QualityMetrics(sharpness=10.0, brightness=100.0, dropped_frames=0),
            pre_event_buffer_s=1.0, post_event_buffer_s=1.0,
            signer=signer,
        )
        pub_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(signer.public_hex()))
        pub_key.verify(bytes.fromhex(pkg.device_signature), pkg.canonical_bytes())  # raises if invalid
    finally:
        shutil.rmtree(tmp)


def test_tampered_package_fails_signature_check():
    tmp = Path(tempfile.mkdtemp())
    try:
        signer = _make_signer(tmp)
        pkg = build_evidence_package(
            device_id="MD-CAM-TEST", video_bytes=b"video-a",
            event_type="motion", confidence=0.5,
            model_version="v0", model_hash="h", firmware_version="fw", firmware_hash="h2",
            quality_metrics=QualityMetrics(sharpness=1, brightness=1, dropped_frames=0),
            pre_event_buffer_s=0.5, post_event_buffer_s=0.5, signer=signer,
        )
        pub_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(signer.public_hex()))
        pkg.confidence = 0.99  # tamper after the fact
        try:
            pub_key.verify(bytes.fromhex(pkg.device_signature), pkg.canonical_bytes())
            raised = False
        except InvalidSignature:
            raised = True
        assert raised, "tampered package must fail signature verification"
    finally:
        shutil.rmtree(tmp)


def test_worm_store_refuses_overwrite_and_ledger_stays_intact():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = WormStore(tmp)
        store.store_evidence("evt_1", {"event_id": "evt_1", "x": 1}, b"video-bytes-1")
        store.store_evidence("evt_2", {"event_id": "evt_2", "x": 2}, b"video-bytes-2")
        assert store.verify_ledger()

        try:
            store.store_evidence("evt_1", {"event_id": "evt_1", "x": 999}, b"different-bytes")
            raised = False
        except FileExistsError:
            raised = True
        assert raised, "WORM store must refuse to overwrite an existing event"
        assert store.verify_ledger()
    finally:
        shutil.rmtree(tmp)


def test_ledger_detects_out_of_band_tampering():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = WormStore(tmp)
        store.store_evidence("evt_1", {"event_id": "evt_1"}, b"video-bytes")
        assert store.verify_ledger()

        # simulate someone hand-editing the ledger file directly: swap in a
        # different (but well-formed) content_hash, as if the evidence file
        # behind this entry had been silently replaced.
        import json
        ledger_path = tmp / "ledger.jsonl"
        lines = ledger_path.read_text().splitlines()
        entry = json.loads(lines[0])
        entry["content_hash"] = "0" * 64
        lines[0] = json.dumps(entry)
        ledger_path.write_text("\n".join(lines) + "\n")
        assert not store.verify_ledger()
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        passed += 1
        print(f"ok  - {t.__name__}")
    print(f"\n{passed}/{len(tests)} tests passed")
