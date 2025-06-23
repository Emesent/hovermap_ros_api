from typing import Callable, List, Tuple

from . import utils


class History:
    """
    A History stores a sequence of timestamped Manifests and enables efficient
    queries for computing sync lags (i.e. how long ago were we fully
    uploaded/downloaded to/from a peer).
    """

    def __init__(self) -> None:
        self._entries: List[Tuple[float, utils.Manifest]] = [(0.0, utils.Manifest())]

    def try_add(self, timestamp: float, manifest: utils.Manifest) -> bool:
        """Try to add a new entry."""
        if manifest.seq > self._entries[-1][1].seq:
            self._entries.append((timestamp, manifest))
            return True
        return False

    def peek(self) -> Tuple[float, utils.Manifest]:
        """Return the most recent entry."""
        return self._entries[-1]

    def _find_most_recent_lte(
        self, is_needle_lt: Callable[[Tuple[float, utils.Manifest]], bool]
    ) -> float:
        """
        Helper function for finding the timestamp of the most recent entry less
        than or equal to the argument via binary search.
        """
        # Set lo = i such that e <= x for all e in a[:i], and e > x for all e in a[i:].
        lo, hi = 0, len(self._entries)
        while lo < hi:
            mid = (lo + hi) // 2
            if is_needle_lt(self._entries[mid]):
                hi = mid
            else:
                lo = mid + 1
        # Then return the element preceding the insertion point.
        return self._entries[lo - 1][0]

    def find_most_recent_lte_seq(self, seq: int) -> float:
        """
        Find the timestamp of the most recent entry with a manifest seq less
        than or equal to the given seq.
        """

        def is_needle_lt(hackstack_entry):
            return seq < hackstack_entry[1].seq

        return self._find_most_recent_lte(is_needle_lt)

    def find_most_recent_lte_tails(self, tails: List[utils.LogIndex]) -> float:
        """
        Find the timestamp of the most recent entry containing only manifest
        tails that are "behind" the argument manifest tails (e.g. the most recent
        time when the database described by this History was a subset of the
        database described by the argument).
        """

        def is_needle_lt(haystack_entry):
            return any(utils.iter_updateable(haystack_entry[1].tails, tails))

        return self._find_most_recent_lte(is_needle_lt)
