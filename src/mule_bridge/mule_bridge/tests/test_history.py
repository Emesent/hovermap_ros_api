

import unittest

import mule_bridge


def size(blobs):
    return sum(map(len, blobs))


class TestHistory(unittest.TestCase):
    def test(self):
        # create an empty History instance
        hist = mule_bridge.History()
        self.assertEqual(hist.peek(), (0.0, mule_bridge.Manifest()))
        node_uuid_1 = b"uuid_1"
        log_name_1 = "log_1"
        trunc_1 = False
        node_uuid_2 = b"uuid_2"
        log_name_2 = "log_2"
        trunc_2 = False

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

    rosunit.unitrun("test_mule_bridge", "test_history", TestHistory)
