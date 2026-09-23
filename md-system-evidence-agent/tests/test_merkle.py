"""
Run directly with: python3 tests/test_merkle.py
(also compatible with `pytest` if you have it installed — functions are
named test_* and use plain asserts.)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.merkle import build_batch, sha256_hex, verify_proof, MerkleTree


def test_root_is_deterministic():
    leaves = [sha256_hex(f"leaf-{i}".encode()) for i in range(5)]
    root1, _ = build_batch(leaves)
    root2, _ = build_batch(list(leaves))
    assert root1 == root2


def test_root_changes_if_any_leaf_changes():
    leaves = [sha256_hex(f"leaf-{i}".encode()) for i in range(6)]
    root_before, _ = build_batch(leaves)
    tampered = list(leaves)
    tampered[3] = sha256_hex(b"tampered-leaf")
    root_after, _ = build_batch(tampered)
    assert root_before != root_after


def test_proof_round_trip_even_count():
    leaves = [sha256_hex(f"leaf-{i}".encode()) for i in range(8)]
    tree = MerkleTree(leaves=leaves)
    for i, leaf in enumerate(leaves):
        proof = tree.proof(i)
        assert verify_proof(leaf, proof, tree.root)


def test_proof_round_trip_odd_count():
    leaves = [sha256_hex(f"leaf-{i}".encode()) for i in range(7)]
    tree = MerkleTree(leaves=leaves)
    for i, leaf in enumerate(leaves):
        proof = tree.proof(i)
        assert verify_proof(leaf, proof, tree.root)


def test_single_leaf_tree():
    leaves = [sha256_hex(b"only-one")]
    tree = MerkleTree(leaves=leaves)
    assert tree.root == leaves[0]
    assert verify_proof(leaves[0], tree.proof(0), tree.root)


def test_proof_fails_against_wrong_leaf():
    leaves = [sha256_hex(f"leaf-{i}".encode()) for i in range(6)]
    tree = MerkleTree(leaves=leaves)
    proof = tree.proof(2)
    assert not verify_proof(sha256_hex(b"not-the-real-leaf"), proof, tree.root)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        passed += 1
        print(f"ok  - {t.__name__}")
    print(f"\n{passed}/{len(tests)} tests passed")
