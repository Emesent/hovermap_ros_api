import unittest

import mule_bridge


def size(blobs):
    return sum(map(len, blobs))


class TestProtocol(unittest.TestCase):
    def test(self):
        ping_seq_1 = 1
        swarm_name_1 = "swarm_1"
        node_name_1 = "mule_1"
        ip_address_1 = "123.45.67.89"
        pong_port_1 = 123
        zsub_port_1 = 456
        zrouter_port_1 = 789

        node_uuid_1 = b"uuid_1"
        log_name_1 = "log_1"
        trunc_1 = False
        blobs_1 = [b"blob_1a"]
        manifest_1 = mule_bridge.Manifest(
            1, [mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, size(blobs_1))]
        )
        budget_1 = 123456789
        updates_1 = [
            mule_bridge.LogChunk(
                mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 0), blobs_1
            )
        ]

        node_uuid_2 = b"uuid_2"
        seq_2 = 1
        lag_2 = 3.5

        sync_lags_1 = [mule_bridge.SyncLag(node_uuid_2, seq_2, lag_2)]

        # test serialisation round-trip
        ping = mule_bridge.Ping(
            ping_seq_1,
            swarm_name_1,
            node_name_1,
            node_uuid_1,
            pong_port_1,
            zsub_port_1,
            zrouter_port_1,
            manifest_1,
            sync_lags_1,
        )
        self.assertEqual(mule_bridge.loads_ping(mule_bridge.dumps_ping(ping)), ping)

        pong = mule_bridge.Pong(ping_seq_1, node_uuid_1)
        self.assertEqual(mule_bridge.loads_pong(mule_bridge.dumps_pong(pong)), pong)

        hello_request = mule_bridge.HelloRequest(
            node_name_1, ip_address_1, zsub_port_1, zrouter_port_1
        )
        self.assertEqual(
            mule_bridge.loads_hello_request(
                mule_bridge.dumps_hello_request(hello_request)
            ),
            hello_request,
        )

        hello_reply = mule_bridge.HelloReply()
        self.assertEqual(
            mule_bridge.loads_hello_reply(mule_bridge.dumps_hello_reply(hello_reply)),
            hello_reply,
        )

        sync_request = mule_bridge.SyncRequest(
            [mule_bridge.LogIndex(node_uuid_1, log_name_1, trunc_1, 0)],
            budget_1,
        )
        self.assertEqual(
            mule_bridge.loads_sync_request(
                mule_bridge.dumps_sync_request(sync_request)
            ),
            sync_request,
        )

        sync_reply = mule_bridge.SyncReply(updates_1)
        self.assertEqual(
            mule_bridge.loads_sync_reply(mule_bridge.dumps_sync_reply(sync_reply)),
            sync_reply,
        )


if __name__ == "__main__":
    import rosunit

    rosunit.unitrun("test_mule_bridge", "test_protocol", TestProtocol)
