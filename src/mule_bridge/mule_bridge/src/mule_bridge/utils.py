import random
from typing import Iterator, List, NamedTuple


class LogIndex(NamedTuple):
    """A LogIndex represents a byte position in a log."""

    node_uuid: bytes
    log_name: str
    trunc: bool
    index: int


class LogChunk(NamedTuple):
    """A LogChunk represents data starting from a certain position in a log."""

    head: LogIndex
    blobs: List[bytes]


class Manifest(NamedTuple):
    """
    A Manifest represents metadata about a collection of logs. It consists of a
    seq and tails. The seq is a non-negative integer that orders the Manifest
    amongst all other others produced by this Database. Each tail is a LogIndex.
    """

    seq: int = 0
    tails: List[LogIndex] = []


class SyncLag(NamedTuple):
    """
    A SyncLag represents an upper bound on the time difference to the most
    recent time when a node's manifest was a superset of a peer's manifest.
    """

    node_uuid: bytes
    manifest_seq: int
    lag: float


def iter_updateable(
    left_tails: List[LogIndex],
    right_tails: List[LogIndex],
) -> Iterator[LogIndex]:
    """Yield right tails that are behind a corresponding left tail."""
    right_tail_indices = {
        (tail.node_uuid, tail.log_name): tail.index for tail in right_tails
    }
    for left_tail in left_tails:
        right_tail_index = right_tail_indices.get(
            (left_tail.node_uuid, left_tail.log_name), 0
        )
        if right_tail_index < left_tail.index:
            yield LogIndex(
                left_tail.node_uuid,
                left_tail.log_name,
                left_tail.trunc,
                right_tail_index,
            )


def clamp(min_val: int, val: int, max_val: int) -> int:
    """Return a value clamped between a minimum and maximum."""
    return max(min_val, min(val, max_val))


def jitter(delay: float, frac: float = 0.25) -> float:
    """Return a delay with random jitter."""
    return delay + (2.0 * (random.random() - 0.5) * delay * frac)
