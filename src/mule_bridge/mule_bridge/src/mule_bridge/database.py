import logging
import os
import sqlite3
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from . import utils

logger = logging.getLogger(__name__)


class Database:
    """A Database is used to store/retrieve blobs, and generate Manifests."""

    def __init__(self, filename: Optional[str] = None) -> None:
        # track tails in a dict structure for efficient queries:
        # (uuid, log_name) keys, (trunc, tail_index) values
        self._logs: Dict[Tuple[bytes, str], Tuple[bool, int]] = {}
        # manifests with different tails should have different sequence
        # numbers, so we use a dirty flag to increment it just in time
        self._seq = 0
        self._dirty = False

        if filename is None:
            self._connection = sqlite3.connect(":memory:")
        else:
            try:
                # In case file already exists, try to remove it
                os.remove(filename)
            except OSError:
                pass
            self._connection = sqlite3.connect(filename)

        self._connection.text_factory = str

        self._connection.execute(
            """
            CREATE TABLE mule_blobs(
                node_uuid BLOB,
                log_name TEXT,
                head_index INTEGER,
                blob BLOB);
            """,
        )
        self._connection.execute(
            """
            CREATE INDEX mule_blobs_index
                ON mule_blobs(node_uuid, log_name);
            """,
        )

    def iter_logs(self) -> Iterator[Tuple[utils.LogChunk, int]]:
        """Yield all data associated with each log.

        Returns: A generator of (chunk, size) values.
        """
        for (node_uuid, log_name), (trunc, _) in self._logs.items():
            yield self._retrieve_chunk(utils.LogIndex(node_uuid, log_name, trunc, 0))

    def get_manifest(self) -> utils.Manifest:
        """Get a summary of the data stored in this Database as a Manifest.

        Returns: A Manifest.
        """
        if self._dirty:
            self._dirty = False
            self._seq += 1
        return utils.Manifest(
            self._seq,
            [
                utils.LogIndex(node_uuid, log_name, trunc, tail_index)
                for (node_uuid, log_name), (trunc, tail_index) in self._logs.items()
            ],
        )

    def assemble_updates(
        self,
        tails: Iterable[utils.LogIndex],
        minimum: Optional[int] = None,
        budget: Optional[int] = None,
    ) -> Tuple[List[utils.LogChunk], int]:
        """
        Assemble updates for a remote Database.

        Args:
            minimum: Optional; Assemble at least this many blobs before considering any budget.
            budget: Optional; Assemble an amount of blob data below or as close to this budget as possible.

        Returns: The update chunks and the total size of all update blobs.
        """
        updates = []
        updates_size = 0
        for tail in tails:
            if (budget is not None and budget <= 0) and (
                minimum is None or minimum <= 0
            ):
                break
            update, size = self._retrieve_chunk(
                utils.LogIndex(tail.node_uuid, tail.log_name, tail.trunc, tail.index),
                minimum,
                budget,
            )
            count = len(update.blobs)
            if count == 0:
                continue
            if minimum is not None:
                minimum -= count
            if budget is not None:
                budget -= size
            updates.append(update)
            updates_size += size
        return updates, updates_size

    def apply_updates(
        self, updates: List[utils.LogChunk]
    ) -> Iterator[Tuple[int, utils.LogChunk, int]]:
        """
        Apply updates from a remote Database.

        Return: A generator that yields (unused_size, used_chunk, used_size) values.
        """
        for chunk in updates:
            # Determine which blobs from the update item to use
            existing_trunc, tail_index = self._logs.get(
                (chunk.head.node_uuid, chunk.head.log_name), (None, 0)
            )
            if existing_trunc is not None and existing_trunc != chunk.head.trunc:
                logger.warn(
                    f"Ignored update item for {chunk.head.node_uuid}/{chunk.head.log_name} with trunc mismatch"
                )
                continue
            unused_count = 0
            unused_size = 0
            apply_index = chunk.head.index
            while apply_index < tail_index and unused_count < len(chunk.blobs):
                size = len(chunk.blobs[unused_count])
                apply_index += size
                unused_size += size
                unused_count += 1
            if not chunk.head.trunc and apply_index != tail_index:
                logger.warn(
                    f"Ignored update item for {chunk.head.node_uuid}/{chunk.head.log_name} with index mismatch"
                )
                continue
            used_blobs = chunk.blobs[unused_count:]
            if used_blobs:
                used_chunk = utils.LogChunk(
                    utils.LogIndex(
                        chunk.head.node_uuid,
                        chunk.head.log_name,
                        chunk.head.trunc,
                        apply_index,
                    ),
                    used_blobs,
                )
                yield unused_size, used_chunk, self._store_chunk(used_chunk)

    def append_blob(
        self, node_uuid: bytes, log_name: str, trunc: bool, blob: bytes
    ) -> None:
        """Append a blob to a log."""
        existing_trunc, tail_index = self._logs.get((node_uuid, log_name), (None, 0))
        if existing_trunc is not None and existing_trunc != trunc:
            logger.warn(f"Ignored add for {node_uuid}/{log_name} with trunc mismatch")
            return
        self._store_chunk(
            utils.LogChunk(
                utils.LogIndex(node_uuid, log_name, trunc, tail_index), [blob]
            )
        )

    def _retrieve_chunk(
        self,
        tail: utils.LogIndex,
        minimum: Optional[int] = None,
        budget: Optional[int] = None,
    ) -> Tuple[utils.LogChunk, int]:
        """
        Retrieve a chunk.

        Args:
            minimum: Optional; Retrieve at least this many blobs before considering any budget.
            budget: Optional; Retrieve an amount of blob data below or as close to this budget as possible.

        Returns: The chunk and the total size of the blobs.
        """
        retrieve_index = tail.index
        blobs = []
        size = 0

        node_uuid_bin = sqlite3.Binary(tail.node_uuid)
        if budget is None:
            cursor = self._connection.execute(
                """
                SELECT head_index, blob
                FROM mule_blobs
                WHERE node_uuid == ? AND log_name == ? AND head_index >= ?;
                """,
                (node_uuid_bin, tail.log_name, retrieve_index),
            )
            for row in cursor.fetchall():
                retrieve_index = retrieve_index if blobs else row[0]
                blob = bytes(row[1])
                blobs.append(blob)
                size += len(blob)

        else:
            if minimum is not None:
                cursor = self._connection.execute(
                    """
                    SELECT head_index, blob
                    FROM mule_blobs
                    WHERE node_uuid == ? AND log_name == ? AND head_index >= ?
                    LIMIT ?;
                    """,
                    (node_uuid_bin, tail.log_name, retrieve_index, minimum),
                )
                for row in cursor.fetchall():
                    retrieve_index = retrieve_index if blobs else row[0]
                    blob = bytes(row[1])
                    blobs.append(blob)
                    size += len(blob)

            budget -= size
            if budget > 0:
                cursor = self._connection.execute(
                    """
                    SELECT head_index, blob
                    FROM mule_blobs
                    WHERE node_uuid == ? AND log_name == ? AND head_index >= ? AND (head_index + length(blob)) <= ?;
                    """,
                    (
                        node_uuid_bin,
                        tail.log_name,
                        retrieve_index + size,
                        retrieve_index + size + budget,
                    ),
                )
                for row in cursor.fetchall():
                    retrieve_index = retrieve_index if blobs else row[0]
                    blob = bytes(row[1])
                    blobs.append(blob)
                    size += len(blob)

        return (
            utils.LogChunk(
                utils.LogIndex(
                    tail.node_uuid, tail.log_name, tail.trunc, retrieve_index
                ),
                blobs,
            ),
            size,
        )

    def _store_chunk(self, chunk: utils.LogChunk) -> int:
        """
        Store a chunk.

        Returns: The total size of the blobs.
        """
        node_uuid_bin = sqlite3.Binary(chunk.head.node_uuid)
        store_index = chunk.head.index

        if chunk.head.trunc:
            self._connection.execute(
                """
                DELETE FROM mule_blobs
                WHERE node_uuid == ? AND log_name == ?;
                """,
                (node_uuid_bin, chunk.head.log_name),
            )

        for i, blob in enumerate(chunk.blobs):
            size = len(blob)
            if not chunk.head.trunc or i == len(chunk.blobs) - 1:
                self._connection.execute(
                    """
                    INSERT INTO mule_blobs
                    VALUES (?, ?, ?, ?);
                    """,
                    (
                        node_uuid_bin,
                        chunk.head.log_name,
                        store_index,
                        sqlite3.Binary(blob),
                    ),
                )
            store_index += size

        self._logs[chunk.head.node_uuid, chunk.head.log_name] = (
            chunk.head.trunc,
            store_index,
        )
        self._dirty = True

        return store_index - chunk.head.index
