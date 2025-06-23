

import unittest

import mule_bridge


def size(blobs):
    return sum(map(len, blobs))


class TestDatabase(unittest.TestCase):
    def test(self):
        # create empty Database instances
        db_1 = mule_bridge.Database()
        db_2 = mule_bridge.Database()
        db_3 = mule_bridge.Database()
        self.assertEqual(db_1.get_manifest(), mule_bridge.Manifest())
        self.assertEqual(db_2.get_manifest(), mule_bridge.Manifest())
        self.assertEqual(db_3.get_manifest(), mule_bridge.Manifest())

        # create some data for a log
        node_uuid_1 = b"uuid_1"
        log_name_1 = "log_1"
        trunc_1 = False
        blobs_1 = [b"blob_1a"]
        size_1 = size(blobs_1)

        # ensure that adding a blob is reflected in the manifest
        db_1.append_blob(node_uuid_1, log_name_1, trunc_1, blobs_1[0])
        self.assertEqual(
            db_1.get_manifest(),
            mule_bridge.Manifest(
                1, [mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, size_1)]
            ),
        )

        # ensure that we can read the blob back out
        self.assertEqual(
            list(db_1.iter_logs()),
            [
                (
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 0),
                        blobs_1,
                    ),
                    size_1,
                )
            ],
        )

        # ensure that the updateable relationship is the right way around
        self.assertEqual(
            list(
                mule_bridge.iter_updateable(
                    db_2.get_manifest().tails, db_1.get_manifest().tails
                )
            ),
            [],
        )
        updateable_tails = list(
            mule_bridge.iter_updateable(
                db_1.get_manifest().tails, db_2.get_manifest().tails
            )
        )
        self.assertEqual(
            updateable_tails,
            [mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 0)],
        )

        # ensure we can assemble an update from db1 for db2
        self.assertEqual(
            db_1.assemble_updates(updateable_tails, 0, 0),
            ([], 0),
        )
        updates, updates_size = db_1.assemble_updates(updateable_tails)
        self.assertEqual(
            (updates, updates_size),
            (
                [
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 0),
                        blobs_1,
                    )
                ],
                size_1,
            ),
        )

        # ensure that we can apply the update
        self.assertEqual(
            list(db_2.apply_updates(updates)),
            [
                (
                    0,
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 0),
                        blobs_1,
                    ),
                    size_1,
                )
            ],
        )

        # ensure that re-applying updates doesn't duplicate it in the database
        self.assertEqual(
            list(db_2.apply_updates(updates)),
            [],
        )
        self.assertEqual(
            db_1.get_manifest().tails,
            db_2.get_manifest().tails,
        )
        self.assertEqual(
            list(db_1.iter_logs()),
            list(db_2.iter_logs()),
        )

        # create some data for a second log
        node_uuid_2 = b"uuid_2"
        log_name_2 = "log_2"
        trunc_2 = False
        blobs_2 = [b"blob_2a", b"blob_2b", b"blob_2c"]
        size_2 = size(blobs_2)

        # ensure we can can append multiple blobs to a different log and see it in the manifest
        db_2.append_blob(node_uuid_2, log_name_2, trunc_2, blobs_2[0])
        db_2.append_blob(node_uuid_2, log_name_2, trunc_2, blobs_2[1])
        db_2.append_blob(node_uuid_2, log_name_2, trunc_2, blobs_2[2])
        self.assertEqual(
            db_2.get_manifest(),
            mule_bridge.Manifest(
                2,
                [
                    mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, size_1),
                    mule_bridge.LogIndex(node_uuid_2, log_name_2, trunc_2, size_2),
                ],
            ),
        )

        # ensure that assemble an update from db2 for db1
        # with a size limit that is only big enough for the first blob
        first_updates, first_updates_size = db_2.assemble_updates(
            mule_bridge.utils.iter_updateable(
                db_2.get_manifest().tails, db_1.get_manifest().tails
            ),
            0,
            size(blobs_2[0:2]) - 1,
        )
        self.assertEqual(
            (first_updates, first_updates_size),
            (
                [
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(node_uuid_2, log_name_2, trunc_2, 0),
                        blobs_2[0:1],
                    )
                ],
                size(blobs_2[0:1]),
            ),
        )

        # ensure we can apply the update
        self.assertEqual(
            list(db_1.apply_updates(first_updates)),
            [
                (
                    0,
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(node_uuid_2, log_name_2, trunc_2, 0),
                        blobs_2[0:1],
                    ),
                    size(blobs_2[0:1]),
                )
            ],
        )

        # ensure that we can assemble an update from db2 for db1
        # with a size limit that is only big enough for the second blob
        # but don't apply it yet!
        second_updates, second_updates_size = db_2.assemble_updates(
            mule_bridge.utils.iter_updateable(
                db_2.get_manifest().tails, db_1.get_manifest().tails
            ),
            0,
            size(blobs_2[1:3]) - 1,
        )
        self.assertEqual(
            (second_updates, second_updates_size),
            (
                [
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(
                            node_uuid_2, log_name_2, trunc_2, size(blobs_2[0:1])
                        ),
                        blobs_2[1:2],
                    )
                ],
                size(blobs_2[1:2]),
            ),
        )

        # ensure that we can assemble an update from db2 for db1
        # with no size limit so it can contain the second and third blobs
        third_updates, third_updates_size = db_2.assemble_updates(
            mule_bridge.iter_updateable(
                db_2.get_manifest().tails, db_1.get_manifest().tails
            )
        )
        self.assertEqual(
            (third_updates, third_updates_size),
            (
                [
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(
                            node_uuid_2, log_name_2, trunc_2, size(blobs_2[0:1])
                        ),
                        blobs_2[1:3],
                    )
                ],
                size(blobs_2[1:3]),
            ),
        )

        # ensure we can apply the second update
        self.assertEqual(
            list(db_1.apply_updates(second_updates)),
            [
                (
                    0,
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(
                            node_uuid_2, log_name_2, trunc_2, size(blobs_2[0:1])
                        ),
                        blobs_2[1:2],
                    ),
                    size(blobs_2[1:2]),
                )
            ],
        )

        # ensure we can apply the third update and recognise that only
        # the third blob is novel
        self.assertEqual(
            list(db_1.apply_updates(third_updates)),
            [
                (
                    size(blobs_2[1:2]),
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(
                            node_uuid_2, log_name_2, trunc_2, size(blobs_2[0:2])
                        ),
                        blobs_2[2:3],
                    ),
                    size(blobs_2[2:3]),
                )
            ],
        )

        # ensure the manifest looks correct
        self.assertEqual(
            db_1.get_manifest(),
            mule_bridge.Manifest(
                3,
                [
                    mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, size_1),
                    mule_bridge.LogIndex(node_uuid_2, log_name_2, trunc_2, size_2),
                ],
            ),
        )

        # ensure we can pull data for multiple logs out of the database
        self.assertEqual(
            list(db_1.iter_logs()),
            [
                (
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 0),
                        blobs_1,
                    ),
                    size_1,
                ),
                (
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(node_uuid_2, log_name_2, trunc_2, 0),
                        blobs_2,
                    ),
                    size_2,
                ),
            ],
        )

        # create some data for a third log that uses a truncated storage policy
        node_uuid_3 = b"uuid_3"
        log_name_3 = "name_3"
        trunc_3 = True
        blobs_3 = [b"blob_3a", b"blob_3b", b"blob_3c"]
        size_3 = size(blobs_3)

        # ensure we can append multiple blobs to a truncated log
        db_3.append_blob(node_uuid_3, log_name_3, trunc_3, blobs_3[0])
        db_3.append_blob(node_uuid_3, log_name_3, trunc_3, blobs_3[1])
        db_3.append_blob(node_uuid_3, log_name_3, trunc_3, blobs_3[2])

        # ensure we can assemble an update from db3 for db2 with a truncated log
        updates, updates_size = db_3.assemble_updates(
            mule_bridge.iter_updateable(
                db_3.get_manifest().tails, db_2.get_manifest().tails
            )
        )

        # ensure we can apply an update with a truncated log
        for _ in db_2.apply_updates(updates):
            pass

        # ensure we can transfer that same data transitively from db2 to db1
        updates, updates_size = db_2.assemble_updates(
            mule_bridge.utils.iter_updateable(
                db_2.get_manifest().tails, db_1.get_manifest().tails
            )
        )
        for _ in db_1.apply_updates(updates):
            pass

        # ensure the manifests look right
        self.assertEqual(
            db_1.get_manifest(),
            mule_bridge.Manifest(
                4,
                [
                    mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, size_1),
                    mule_bridge.LogIndex(node_uuid_2, log_name_2, trunc_2, size_2),
                    mule_bridge.LogIndex(node_uuid_3, log_name_3, trunc_3, size_3),
                ],
            ),
        )

        # ensure that we can pull data for multiple logs including a truncated log
        self.assertEqual(
            list(db_1.iter_logs()),
            [
                (
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 0),
                        blobs_1,
                    ),
                    size_1,
                ),
                (
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(node_uuid_2, log_name_2, trunc_2, 0),
                        blobs_2,
                    ),
                    size_2,
                ),
                (
                    mule_bridge.LogChunk(
                        mule_bridge.LogIndex(
                            node_uuid_3, log_name_3, trunc_3, size(blobs_3[0:2])
                        ),
                        blobs_3[2:3],
                    ),
                    size(blobs_3[2:3]),
                ),
            ],
        )

        # create an empty History instance
        hist = mule_bridge.History()
        self.assertEqual(hist.peek(), (0.0, mule_bridge.Manifest()))

        # add some entries
        self.assertEqual(
            hist.try_add(
                1.0,
                mule_bridge.Manifest(
                    1, [mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 1)]
                ),
            ),
            True,
        )
        self.assertEqual(
            hist.try_add(
                1.0,
                mule_bridge.Manifest(
                    1, [mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 1)]
                ),
            ),
            False,
        )
        self.assertEqual(
            hist.try_add(
                2.0,
                mule_bridge.Manifest(
                    2,
                    [
                        mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 1),
                        mule_bridge.LogIndex(node_uuid_2, log_name_2, trunc_2, 2),
                    ],
                ),
            ),
            True,
        )
        self.assertEqual(
            hist.peek(),
            (
                2.0,
                mule_bridge.Manifest(
                    2,
                    [
                        mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 1),
                        mule_bridge.LogIndex(node_uuid_2, log_name_2, trunc_2, 2),
                    ],
                ),
            ),
        )

        # do some seq-based lookups
        self.assertEqual(hist.find_most_recent_lte_seq(0), 0.0)
        self.assertEqual(hist.find_most_recent_lte_seq(1), 1.0)
        self.assertEqual(hist.find_most_recent_lte_seq(2), 2.0)
        self.assertEqual(hist.find_most_recent_lte_seq(3), 2.0)

        # do some item-based lookups
        self.assertEqual(hist.find_most_recent_lte_tails([]), 0.0)
        self.assertEqual(
            hist.find_most_recent_lte_tails(
                [
                    mule_bridge.LogIndex(node_uuid_1, log_name_1, True, 1),
                ]
            ),
            1.0,
        )
        self.assertEqual(
            hist.find_most_recent_lte_tails(
                [
                    mule_bridge.LogIndex(node_uuid_1, log_name_1, True, 1),
                    mule_bridge.LogIndex(node_uuid_2, log_name_2, True, 1),
                ]
            ),
            1.0,
        )
        self.assertEqual(
            hist.find_most_recent_lte_tails(
                [
                    mule_bridge.LogIndex(node_uuid_1, log_name_1, True, 1),
                    mule_bridge.LogIndex(node_uuid_2, log_name_2, True, 2),
                ]
            ),
            2.0,
        )
        self.assertEqual(
            hist.find_most_recent_lte_tails(
                [
                    mule_bridge.LogIndex(node_uuid_1, log_name_1, True, 2),
                    mule_bridge.LogIndex(node_uuid_2, log_name_2, True, 2),
                ]
            ),
            2.0,
        )


if __name__ == "__main__":
    import rosunit

    rosunit.unitrun("test_mule_bridge", "test_database", TestDatabase)
