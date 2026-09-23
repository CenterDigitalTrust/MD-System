"""
Binary Merkle tree over SHA-256 leaf hashes.

Matches the batching scheme described in the MD System pilot guide:
- leaves are event hashes (already hex-encoded sha256 strings)
- odd levels duplicate the last node (Bitcoin-style) rather than leaving
  a lone node unpaired
- the root is what gets anchored on-chain; individual leaves stay off-chain
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List, Tuple


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_pair(left: str, right: str) -> str:
    return sha256_hex((left + right).encode("utf-8"))


@dataclass
class MerkleProofStep:
    sibling: str
    # "L" means the sibling sits to the left of our running hash,
    # "R" means it sits to the right.
    position: str


@dataclass
class MerkleTree:
    leaves: List[str]
    levels: List[List[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.leaves:
            raise ValueError("MerkleTree needs at least one leaf")
        self.levels = self._build_levels(list(self.leaves))

    @staticmethod
    def _build_levels(level: List[str]) -> List[List[str]]:
        levels = [level]
        while len(level) > 1:
            nxt: List[str] = []
            for i in range(0, len(level), 2):
                left = level[i]
                right = level[i + 1] if i + 1 < len(level) else level[i]
                nxt.append(_hash_pair(left, right))
            level = nxt
            levels.append(level)
        return levels

    @property
    def root(self) -> str:
        return self.levels[-1][0]

    def proof(self, index: int) -> List[MerkleProofStep]:
        """Return the sibling path needed to recompute the root from leaf `index`."""
        if index < 0 or index >= len(self.leaves):
            raise IndexError("leaf index out of range")
        steps: List[MerkleProofStep] = []
        idx = index
        for level in self.levels[:-1]:
            is_right = idx % 2 == 1
            pair_idx = idx - 1 if is_right else idx + 1
            if pair_idx >= len(level):
                pair_idx = idx  # odd node paired with itself
            sibling = level[pair_idx]
            steps.append(MerkleProofStep(sibling=sibling, position="L" if is_right else "R"))
            idx //= 2
        return steps


def verify_proof(leaf: str, proof: List[MerkleProofStep], root: str) -> bool:
    running = leaf
    for step in proof:
        if step.position == "R":
            running = _hash_pair(running, step.sibling)
        else:
            running = _hash_pair(step.sibling, running)
    return running == root


def build_batch(leaves: List[str]) -> Tuple[str, MerkleTree]:
    """Convenience wrapper: build a tree and return (root, tree)."""
    tree = MerkleTree(leaves=leaves)
    return tree.root, tree
