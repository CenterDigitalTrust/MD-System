# MD System — Edge Evidence Agent (golden path reference implementation)

Reference implementation of the "M1 — Golden path" milestone from the MD
System pilot guide:

```
camera → event detection → evidence package → Merkle batch
       → Solana commitment (or offline queue) → WORM storage
```

Every video segment and metadata blob is hashed with SHA-256 on the
device, signed with a device Ed25519 key, batched into a Merkle tree, and
only the **Merkle root** — never raw video or personal data — is anchored
on Solana (via the public Memo program, devnet by default). The evidence
itself stays in local WORM-style storage (a stand-in for S3 Object Lock).

This runs on a laptop with a webcam or a video file — no Jetson, no real
camera, no funded Solana wallet required to try it.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# against your webcam
python -m src.agent --source 0

# against a video file (useful for repeatable testing)
python -m src.agent --source path/to/sample.mp4

# against a real ONVIF/RTSP camera, once you have one on the bench
python -m src.agent --source rtsp://192.168.1.50:554/stream1
```

Ctrl+C stops the agent cleanly and flushes any partial batch. Output for
every event/batch is also printed to stdout as it happens, e.g.:

```
[agent] device_id=MD-CAM-DEV-001 source=0 solana_enabled=False
[event] evt_492b919a74 type=motion confidence=0.87 hash=82766386e613959e…
[batch] batch_dc99254629 events=6 root=658cebb6e39d8e88… status=queued
[agent] stopped. ledger intact: True
```

Everything lands under `./data/`:

```
data/
  evidence/<event_id>.json     # sealed evidence package (write-once)
  segments/<event_id>.bin      # the actual video clip, sealed alongside it
  batches/<batch_id>.json      # Merkle root + per-event proofs + anchor result
  ledger.jsonl                 # hash-chained write log (detects tampering)
  audit_log.jsonl              # who/what/when/why accessed something
  pending_commitments.jsonl    # commitments queued while Solana is offline/disabled
  keys/device_key.raw          # this device's signing key (generated on first run)
```

## Run the tests

No pytest required (works with it too, if installed):

```bash
python3 tests/test_merkle.py
python3 tests/test_evidence_storage.py
```

These cover: Merkle root determinism and tamper-sensitivity, proof
generation/verification for even and odd leaf counts, device-signature
verification (and failure on tampering), and WORM write-once + ledger
tamper-detection.

## Enabling real Solana Devnet anchoring

Off by default (`solana.enabled: false` in `config.yaml`) so the pipeline
runs with zero blockchain setup. To turn it on:

```bash
pip install solana solders
solana-keygen new -o keys/evidence_signer.json   # Solana CLI, or generate via solders
solana airdrop 1 <pubkey> --url devnet            # fund it with devnet SOL (free, testnet only)
```

Then in `config.yaml`:

```yaml
solana:
  enabled: true
  rpc_url: https://api.devnet.solana.com
  keypair_path: ./keys/evidence_signer.json
```

If the network is unreachable or the keypair is missing, commitments are
queued locally instead of raising (`data/pending_commitments.jsonl`) —
mirroring MD-CAM's STEALTH (offline) / SYNC (online) behaviour. Call
`SolanaAnchor.flush_pending()` once connectivity is back.

**Key separation matters**: the Evidence Signer keypair used here should
only ever submit memo transactions — never reuse a mint authority or
treasury key for this, per the pilot guide's threat model (section 14).

## What this is / is not

This is a **reference implementation of the golden path**, meant to prove
the architecture end-to-end and to serve as the open-source component of
the project (see the Solana Foundation grant draft). It is *not*
production-ready as-is:

| Here (dev/pilot) | Needed for production |
|---|---|
| OpenCV background-subtraction "motion" heuristic | Real trained CV model (TensorRT/DeepStream) for motion/person/vehicle/tamper classes |
| Local filesystem, chmod-read-only WORM approximation | Real S3 Object Lock (or equivalent) WORM storage |
| Device key generated and stored as a plain file | HSM-backed or hardware-attested device keys |
| Basic actor/role/purpose audit log | Full КЕП-based identity + role/purpose/scope access control (pilot guide section 15) |
| Memo-program commitment on Devnet | Production Solana cluster, monitored, with a dedicated non-custodial Evidence Signer under proper key management |

## License

MIT — see `LICENSE`. This is the open component; the MD-CAM hardware
design and the Miracle Droplet MD™ brand/licensing are handled
separately.
