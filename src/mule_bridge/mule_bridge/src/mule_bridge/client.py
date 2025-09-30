import collections
import functools
import logging
import random
import socket
import struct
import zlib
from typing import Any, Callable, Iterator, List, NamedTuple, Optional, Tuple

import netifaces
import zmq
import zmq.utils.monitor
from tornado.ioloop import IOLoop
from zmq.eventloop.zmqstream import ZMQStream

from . import beacon, config, database, history, protocol, utils

logger = logging.getLogger(__name__)

# Message tag constants
_TAG_HELLO = b"\x00"
_TAG_SYNC = b"\x01"


def _to_zrouting_id(node_uuid: bytes) -> bytes:
    """Convert a node UUID to a ZMQ routing ID."""
    # ZMQ reserves identities starting with \x00
    return b"\x01" + node_uuid


def _from_zrouting_id(zrouting_id: bytes) -> bytes:
    """Convert a ZMQ routing ID to a node UUID."""
    if not zrouting_id.startswith(b"\x01"):
        raise RuntimeError(f"Invalid ZMQ routing ID: {zrouting_id}")
    return zrouting_id[1:]


def _to_zprefix(key: str) -> bytes:
    """Create a ZMQ prefix suitable for exact key matching."""
    # ZMQ uses prefix matching for subscription filtering but we want exact matching
    # so we prepend a 2-byte length to our key (hence it must be less than 65535 bytes).
    b = key.encode("utf-8", "strict")
    n = len(b)
    if n > 65535:
        raise RuntimeError(f"Invalid key length: {key}")
    return b"".join((struct.pack("<H", n), b))


def _to_zframe(key: str, data: bytes) -> bytes:
    """Create a ZMQ frame that can be filtered by exact key matching."""
    return b"".join((_to_zprefix(key), data))


def _from_zframe(zframe: bytes) -> Tuple[str, bytes]:
    """Convert a prefixed ZMQ frame to topic data."""
    zframe_len = len(zframe)
    if zframe_len < 2:
        raise RuntimeError(f"Invalid ZMQ frame size: {zframe_len}")
    topic_key_len = struct.unpack("<H", zframe[0:2])[0]
    zprefix_len = 2 + topic_key_len
    if zframe_len < zprefix_len:
        raise RuntimeError(f"Invalid ZMQ frame content: {zframe}")
    topic_name = zframe[2:zprefix_len].decode("utf-8", "strict")
    msg_buff = zframe[zprefix_len:]
    return topic_name, msg_buff


def _find_interface(ip_prefix) -> str:
    """Find the first network interface IP matching an IP prefix."""

    def to_u32(buf):
        return struct.unpack("!I", buf)[0]

    ip_prefix_u32 = to_u32(socket.inet_aton(ip_prefix))
    for interface in netifaces.interfaces():
        ifaddresses = netifaces.ifaddresses(interface)
        for ip in ifaddresses.get(netifaces.AF_INET, []):
            ip_address = ip["addr"]
            ip_netmask = ip["netmask"]
            try:
                ip_address_u32 = to_u32(socket.inet_aton(ip_address))
                ip_netmask_u32 = to_u32(socket.inet_aton(ip_netmask))
                if (ip_address_u32 & ip_netmask_u32) == ip_prefix_u32:
                    return ip_address
            except socket.error:
                continue
    raise RuntimeError("Failed to find a matching network interface")


class Peer:
    """A Peer aggregates state associated with a discovered peer node."""

    def __init__(
        self,
        node_uuid: bytes,
        node_name: str,
        generation: int,
        zsub_endpoint: str,
        zrouter_endpoint: str,
        zdealer_stream: ZMQStream,
        zmonitor_stream: ZMQStream,
    ) -> None:
        # Members with leading underscores should only be used by Client

        self.node_uuid = node_uuid
        self.node_name = node_name
        self.generation = generation
        self.manifest_time = 0.0
        self.manifest = utils.Manifest()

        self._zsub_endpoint = zsub_endpoint
        self._zrouter_endpoint = zrouter_endpoint
        self._zdealer_stream = zdealer_stream
        self._zmonitor_stream = zmonitor_stream
        self._zdealer_tag: Optional[bytes] = None
        self._zdealer_timeout: Optional[Any] = None

        self._rtt_start_time: Optional[float] = None
        self._rtt_deque = collections.deque()
        self.rtt_mean_secs = 0.0
        self.rtt_success_count = 0
        self.rtt_failure_count = 0

        self._sync_start_time: Optional[float] = None
        self.sync_up_time = 0.0
        self.sync_down_time = 0.0
        self.sync_up_size = 0
        self.sync_down_size = 0
        self.sync_down_used_size = 0
        self.sync_down_budget_size = 0

        self.send_hello_request_count = 0
        self.send_hello_reply_count = 0
        self.send_sync_request_count = 0
        self.send_sync_reply_count = 0
        self.recv_hello_request_count = 0
        self.recv_hello_reply_count = 0
        self.recv_sync_request_count = 0
        self.recv_sync_reply_count = 0


class Swarm:
    """A Swarm manages a collection of Peer instances."""

    def __init__(self) -> None:
        self._peers_by_name = {}
        self._peers_by_uuid = {}

    def __iter__(self) -> Iterator[Peer]:
        return iter(self._peers_by_name.values())

    def get_peer_by_name(self, node_name: str) -> Optional[Peer]:
        """Get a Peer via its unicode-string node-name."""
        return self._peers_by_name.get(node_name)

    def get_peer_by_uuid(self, node_uuid: bytes) -> Optional[Peer]:
        """Get a Peer via its byte-string UUID."""
        return self._peers_by_uuid.get(node_uuid)

    def add_peer(self, node_uuid: bytes, node_name: str, peer: Peer) -> None:
        """Add a Peer to the swarm."""
        assert node_name not in self._peers_by_name, "Bad swarm state"
        assert node_uuid not in self._peers_by_uuid, "Bad swarm state"
        self._peers_by_name[node_name] = peer
        self._peers_by_uuid[node_uuid] = peer

    def remove_peer(self, peer: Peer) -> None:
        """Remove a Peer from the swarm."""
        del self._peers_by_name[peer.node_name]
        del self._peers_by_uuid[peer.node_uuid]


class VolatileCallbackArgs(NamedTuple):
    topic_name: str
    msg_buff: bytes
    bridged_size: int


class PersistentCallbackArgs(NamedTuple):
    topic_name: str
    msg_buff: bytes
    bridged_size: int


class Client:
    """
    A Client provides an interface to communication with the swarm.

    Discovery is handled via a Beacon, and bridging is handled via ZMQ sockets.

    Volatile data is bridged using one-way, fan-out communication.
    Persistent data is bridged using two-way, client-server communication.

    Note: ZMQ supports multiple transport protocols. We chose TCP as it is well
    supported by ZMQ and lets us leverage a mature ecosystem of network tools.
    Future development of this software of may explore the use of different
    transport protocols, e.g. a reliable-multicast protocol such as Norm may be
    preferred for applications that need to be more efficient over a shared
    collision domain on a dense wireless network.
    """

    def __init__(
        self,
        clock: Callable[[], float],
        config: config.Config,
        ioloop: IOLoop,
        zcontext: zmq.Context,
        node_uuid: bytes,
        volatile_topic_names: List[str],
        persistent_topic_names: List[str],
    ) -> None:
        self._clock = clock
        self._config = config
        self._ioloop = ioloop
        self._zcontext = zcontext
        self._node_uuid = node_uuid
        self._volatile_topic_names = volatile_topic_names
        self._persistent_topic_names = persistent_topic_names

        self._compressor = lambda cobj: zlib.compress(cobj, config.compression_level)
        self._decompressor = zlib.decompress
        self._stream_compressors = collections.defaultdict(
            lambda: functools.partial(
                lambda cobj, s: cobj.compress(s) + cobj.flush(zlib.Z_SYNC_FLUSH),
                zlib.compressobj(config.compression_level)
            )
        )
        self._stream_decompressors = collections.defaultdict(
            lambda: functools.partial(
                lambda cobj, s: cobj.decompress(s),
                zlib.decompressobj(),
            )
        )

        self._ip_address = _find_interface(self._config.ip_prefix)
        self._database = database.Database(f"mule_{self._config.node_name}.db")
        self._history = history.History()
        self._swarm = Swarm()
        self._overlay = set()
        self._volatile_callback = None
        self._persistent_callback = None

        self._setup_zsocks()
        self._setup_beacon()

        self._ioloop.add_callback(self._discover_peers)

    def get_history(self) -> history.History:
        """Return the history."""
        return self._history

    def get_peers(self) -> Iterator[Peer]:
        """Return an iterator over peers."""
        return iter(self._swarm)

    def on_volatile(self, callback: Callable[[VolatileCallbackArgs], None]) -> None:
        """Set the callback for handling volatile topic data from the swarm."""
        self._volatile_callback = callback

    def on_persistent(self, callback: Callable[[PersistentCallbackArgs], None]) -> None:
        """Set the callback for handling persistent topic data from the swarm."""
        self._persistent_callback = callback

    def bridge_volatile(self, msg_buff: bytes, flow_name: str, topic_name: str) -> int:
        """Bridge volatile data to the swarm and return the effective size."""
        blob = self._compressor(msg_buff)
        self._send_zsub_message(flow_name, _to_zframe(topic_name, blob))
        return len(blob)

    def bridge_persistent(self, msg_buff: bytes, log_name: str, topic_name: str) -> int:
        """Bridge persistent data to the swarm and return the effective size."""
        log = self._config.bridge.persistent.logs[log_name]
        compressor = (
            self._compressor
            if log.trunc
            else self._stream_compressors[self._node_uuid, log_name]
        )
        blob = compressor(_to_zframe(topic_name, msg_buff))
        self._database.append_blob(self._node_uuid, log_name, log.trunc, blob)
        return len(blob)

    def set_overlay(self, node_names: List[str]) -> None:
        """Restrict outgoing sync requests to a subset of swarm peers."""
        self._overlay = set(node_names)
        self._sync_peers()

    def _setup_zsocks(self) -> None:
        """Setup ZMQ sockets."""
        # We set several ZMQ socket options for sockets:
        # - router handover to allow reconnection with static identity values
        # - connect timeout to avoid exponential connection backoffs
        # - retransmit timeout to avoid exponential retransmission backoffs
        # - heartbeat to ensure timely closure of inactive sockets on the server side
        # - tos to control traffic priorities
        # - sndhwm to control application transmit buffer sizes (use with caution)
        # - sndbuf to control kernel transmit buffer sizes

        zaddr = f"tcp://{self._ip_address}"
        self._zpub_socks = {}
        for flow_name, flow in self._config.bridge.volatile.flows.items():
            zpub_sock = self._zcontext.socket(zmq.PUB)
            zpub_sock.bind_to_random_port(
                zaddr, min_port=self._config.min_port, max_port=self._config.max_port
            )
            zpub_sock.setsockopt(zmq.LINGER, 0)
            zpub_sock.setsockopt(zmq.TOS, flow.ip_tos)
            zpub_sock.setsockopt(zmq.SNDHWM, flow.sndhwm)
            zpub_sock.setsockopt(zmq.SNDBUF, flow.sndbuf)
            zpub_sock.setsockopt(
                zmq.CONNECT_TIMEOUT, int(self._config.volatile_tcp_maxrt * 1000)
            )
            zpub_sock.setsockopt(
                zmq.TCP_MAXRT, int(self._config.volatile_tcp_maxrt * 1000)
            )
            self._zpub_socks[flow_name] = zpub_sock

        self._zsub_stream = ZMQStream(self._zcontext.socket(zmq.SUB), self._ioloop)
        self._zsub_stream.setsockopt(zmq.LINGER, 0)
        self._zsub_stream.setsockopt(
            zmq.HEARTBEAT_IVL, int(self._config.volatile_heartbeat_ivl * 1000)
        )
        self._zsub_stream.setsockopt(
            zmq.HEARTBEAT_TIMEOUT,
            int(self._config.volatile_heartbeat_timeout * 1000),
        )
        self._zsub_stream.setsockopt(
            zmq.HEARTBEAT_TTL,
            int(self._config.volatile_heartbeat_timeout * 1000),
        )

        for topic_name in self._volatile_topic_names:
            self._zsub_stream.setsockopt(zmq.SUBSCRIBE, _to_zprefix(topic_name))
        self._zsub_stream.on_recv(self._handle_zsub_message)
        self._zsub_port = self._zsub_stream.bind_to_random_port(
            zaddr, min_port=self._config.min_port, max_port=self._config.max_port
        )
        logger.debug(f"Bound ZMQ sub socket on {self._zsub_port}")

        self._zrouter_stream = ZMQStream(
            self._zcontext.socket(zmq.ROUTER), self._ioloop
        )
        self._zrouter_stream.setsockopt(zmq.LINGER, 0)
        self._zrouter_stream.setsockopt(zmq.TOS, self._config.persistent_ip_tos)
        self._zrouter_stream.setsockopt(zmq.ROUTER_HANDOVER, 1)
        self._zrouter_stream.setsockopt(
            zmq.HEARTBEAT_IVL, int(self._config.persistent_heartbeat_ivl * 1000)
        )
        self._zrouter_stream.setsockopt(
            zmq.HEARTBEAT_TIMEOUT,
            int(self._config.persistent_heartbeat_timeout * 1000),
        )
        self._zrouter_stream.setsockopt(
            zmq.HEARTBEAT_TTL,
            int(self._config.persistent_heartbeat_timeout * 1000),
        )
        self._zrouter_stream.on_recv(self._handle_zrouter_message)
        self._zrouter_port = self._zrouter_stream.bind_to_random_port(
            zaddr, min_port=self._config.min_port, max_port=self._config.max_port
        )
        logger.debug(f"Bound ZMQ router socket on {self._zrouter_port}")

    def _setup_beacon(self) -> None:
        """Sets up a Beacon for dynamic-discovery."""
        self._beacon = beacon.Beacon(
            self._config,
            self._ioloop,
            self._node_uuid,
            self._ip_address,
            self._zsub_port,
            self._zrouter_port,
        )
        self._beacon.on_ping(self._handle_beacon_ping)
        self._beacon.on_pong(self._handle_beacon_pong)

    def _handle_beacon_ping(self, args: beacon.PingCallbackArgs) -> None:
        """Handle a ping."""
        peer = self._try_add_peer(
            args.node_uuid,
            args.node_name,
            args.ip_address,
            args.zsub_port,
            args.zrouter_port,
        )
        if peer is None or peer.manifest.seq >= args.manifest.seq:
            return

        now = self._clock()
        peer.manifest_time = now
        peer.manifest = args.manifest

        # Update peer sync-up time (i.e. when we were 'fully uploaded' to peer)
        manifest_time = self._history.find_most_recent_lte_tails(args.manifest.tails)
        if manifest_time > peer.sync_up_time:
            peer.sync_up_time = manifest_time

        # Update peer sync-down time (i.e. when we were 'fully downloaded' from peer)
        for sync_lag in args.sync_lags:
            if sync_lag.node_uuid != self._node_uuid:
                continue
            manifest_time = (
                self._history.find_most_recent_lte_seq(sync_lag.manifest_seq)
                - sync_lag.lag
            )
            if manifest_time > peer.sync_down_time:
                peer.sync_down_time = manifest_time
            break

        self._sync_peers()

    def _handle_beacon_pong(self, args: beacon.PongCallbackArgs) -> None:
        """Handle a pong."""
        peer = self._swarm.get_peer_by_uuid(args.node_uuid)
        if peer is None or peer._rtt_start_time is None:
            return
        now = self._clock()
        peer._rtt_deque.append((now, now - peer._rtt_start_time))
        peer._rtt_start_time = None

    def _handle_zsub_message(self, zframes: List[bytes]) -> None:
        """Handle a message from a ZMQ sub socket."""
        n = len(zframes)
        if n != 1:
            logger.debug(f"Invalid ZMQ sub message with {n} frames")
            return

        try:
            topic_name, msg_buff = _from_zframe(zframes[0])
            bridged_size = len(msg_buff)
            msg_buff = self._decompressor(msg_buff)
        except (RuntimeError, zlib.error):
            logger.warning("Error loading ZMQ sub message", exc_info=True)
            return

        if topic_name not in self._volatile_topic_names:
            logger.debug(f"Ignored ZMQ sub message with topic name {topic_name}")
            return

        if self._volatile_callback:
            self._volatile_callback(
                VolatileCallbackArgs(topic_name, msg_buff, bridged_size)
            )

    def _handle_zrouter_message(self, zframes: List[bytes]) -> None:
        """Handle a message from the ZMQ router socket."""
        n = len(zframes)
        if n != 3:
            logger.debug(f"Invalid ZMQ router message with {n} frames")
            return
        zrouting_id, tag, request = zframes
        try:
            node_uuid = _from_zrouting_id(zrouting_id)
        except RuntimeError:
            logger.warning("Error loading ZMQ router message", exc_info=True)
            return
        if tag == _TAG_HELLO:
            self._process_hello_request(node_uuid, request)
        elif tag == _TAG_SYNC:
            self._process_sync_request(node_uuid, request)
        else:
            logger.debug(f"Ignored ZMQ router message with tag {tag}")

    def _handle_zdealer_message(self, peer: Peer, frames: List[bytes]) -> None:
        """Handle a message from a peer ZMQ dealer socket."""
        n = len(frames)
        if n != 2:
            logger.debug(f"Ignored ZMQ dealer message with {n} frames")
            return
        tag, reply = frames
        if tag != peer._zdealer_tag:
            logger.debug(f"Ignored ZMQ dealer message with tag {tag}")
            return
        peer._zdealer_tag = None
        self._ioloop.remove_timeout(peer._zdealer_timeout)
        peer._zdealer_timeout = None

        if tag == _TAG_HELLO:
            self._process_hello_reply(peer, reply)
        elif tag == _TAG_SYNC:
            self._process_sync_reply(peer, reply)
        else:
            logger.debug(f"Ignored ZMQ dealer message with tag {tag}")

    def _handle_zmonitor_message(self, peer: Peer, frames: List[bytes]) -> None:
        """Handle a message from a peer ZMQ monitor socket."""
        zevent = zmq.utils.monitor.parse_monitor_message(frames)
        zevent_type = zevent["event"]
        zevent_endpoint = zevent["endpoint"].decode("utf-8")

        if zevent_type == zmq.EVENT_CONNECTED:
            self._ioloop.remove_timeout(peer._zdealer_timeout)
            peer._zdealer_timeout = None
            peer.sync_down_budget_size = self._config.sync_budget_min
            logger.info(f"Connected to {peer.node_name} at {zevent_endpoint}")
            self._send_zdealer_message(
                peer,
                _TAG_HELLO,
                protocol.dumps_hello_request(
                    protocol.HelloRequest(
                        self._config.node_name,
                        self._ip_address,
                        self._zsub_port,
                        self._zrouter_port,
                    )
                ),
            )
            peer.send_hello_request_count += 1
            logger.debug(f"Sent hello request to {peer.node_name}")

        elif zevent_type == zmq.EVENT_DISCONNECTED:
            logger.info(f"Disconnected from {peer.node_name} at {zevent_endpoint}")
            self._reset_peer(peer)

    def _send_zsub_message(self, flow_name: str, frame: bytes) -> None:
        """Send a message to a ZMQ pub socket."""
        self._zpub_socks[flow_name].send(frame)

    def _send_zdealer_message(self, peer: Peer, tag: bytes, payload: bytes) -> None:
        """Send a message to a (non-busy) Peer."""
        assert peer._zdealer_timeout is None, "Bad peer state"
        peer._zdealer_timeout = self._ioloop.call_later(
            self._config.persistent_exchange_timeout,
            functools.partial(self._reset_peer, peer),
        )
        peer._zdealer_tag = tag
        peer._zdealer_stream.send_multipart([tag, payload])

    def _process_hello_request(self, node_uuid: bytes, request: bytes) -> None:
        """Handle a hello request from a Peer."""
        try:
            (
                node_name,
                ip_address,
                zsub_port,
                zrouter_port,
            ) = protocol.loads_hello_request(request)
        except protocol.LoadError:
            logger.warning("Error loading hello request", exc_info=True)
            return

        if node_uuid == self._node_uuid:
            logger.debug("Ignored hello request with local node UUID")
            return

        if node_name == self._config.node_name:
            logger.debug("Ignored hello request with local node name")
            return

        peer = self._try_add_peer(
            node_uuid, node_name, ip_address, zsub_port, zrouter_port
        )
        if peer is not None:
            peer.recv_hello_request_count += 1
            self._zrouter_stream.send_multipart(
                [
                    _to_zrouting_id(node_uuid),
                    _TAG_HELLO,
                    protocol.dumps_hello_reply(protocol.HelloReply()),
                ]
            )
            peer.send_hello_reply_count += 1
            logger.debug(f"Sent hello reply to {node_name}")

    def _process_hello_reply(self, peer: Peer, reply: bytes) -> None:
        """Handle a hello reply from a peer."""
        try:
            _ = protocol.loads_hello_reply(reply)
        except protocol.LoadError:
            logger.warning("Error loading hello reply", exc_info=True)
            return
        peer.recv_hello_reply_count += 1
        self._sync_peers()

    def _process_sync_request(self, node_uuid: bytes, request: bytes) -> None:
        """Handle a sync request from a peer."""
        peer = self._swarm.get_peer_by_uuid(node_uuid)
        if peer is None:
            logger.debug(f"Ignored sync request with peer UUID {node_uuid}")
            return
        try:
            sync_request = protocol.loads_sync_request(self._decompressor(request))
        except (protocol.LoadError, zlib.error):
            logger.warning("Error loading sync request", exc_info=True)
            return

        peer.recv_sync_request_count += 1

        # It is possible that a request may be significantly delayed so we
        # modify the request in case a manifest has declared newer data.
        sync_request_indices = {
            (node_uuid, log_name): index
            for index, (node_uuid, log_name, _, _) in enumerate(sync_request.tails)
        }
        for tail in peer.manifest.tails:
            sync_request_index = sync_request_indices.get(
                (tail.node_uuid, tail.log_name)
            )
            if sync_request_index is None:
                continue
            if tail.index > sync_request.tails[sync_request_index].index:
                sync_request.tails[sync_request_index] = tail

        updates, updates_size = self._database.assemble_updates(
            sync_request.tails, 1, sync_request.budget
        )
        self._zrouter_stream.send_multipart(
            [
                _to_zrouting_id(node_uuid),
                _TAG_SYNC,
                protocol.dumps_sync_reply(protocol.SyncReply(updates)),
            ]
        )
        peer.sync_up_size += updates_size
        peer.send_sync_reply_count += 1
        logger.debug(f"Sent sync reply to {peer.node_name}")

    def _process_sync_reply(self, peer: Peer, reply: bytes) -> None:
        """Handle a sync reply from a Peer."""
        assert peer._sync_start_time is not None, "Bad peer state"
        try:
            sync_reply = protocol.loads_sync_reply(reply)
        except protocol.LoadError:
            logger.warning("Error loading sync reply", exc_info=True)
            return
        peer.recv_sync_reply_count += 1
        for unused_size, used_chunk, used_size in self._database.apply_updates(
            sync_reply.updates
        ):
            peer.sync_down_size += unused_size + used_size
            peer.sync_down_used_size += used_size
            decompressor = (
                self._decompressor
                if used_chunk.head.trunc
                else self._stream_decompressors[
                    used_chunk.head.node_uuid, used_chunk.head.log_name
                ]
            )
            try:
                for blob in used_chunk.blobs:
                    bridged_size = len(blob)
                    topic_name, msg_buff = _from_zframe(decompressor(blob))
                    if topic_name not in self._persistent_topic_names:
                        continue
                    if self._persistent_callback:
                        self._persistent_callback(
                            PersistentCallbackArgs(topic_name, msg_buff, bridged_size)
                        )
            except (protocol.LoadError, zlib.error):
                logger.warning("Error loading sync reply", exc_info=True)

        # Adjust the sync budget to try and meet the target reply deadline.
        # This is motivated by the following observations:
        # 1. When latency is high and throughput is low we want to use a
        # small budget to remain responsive to changes in swarm topology and
        # reduce the amount of redundant reply data.
        # 2. When latency is low and throughput is high we want to use a
        # large budget to reduce network and processing overheads.
        # Note: as there is no delay imposed between exchanges, this is not
        # a rate-limited, rather, it is intended to improve performance when
        # operating in highly dynamic conditions.
        cost = len(reply)
        if cost > 0:
            budget = float(peer.sync_down_budget_size)
            target_rate = budget / float(self._config.sync_budget_target_duration)
            duration = self._clock() - peer._sync_start_time
            actual_rate = None if duration <= 0.0 else float(cost) / duration

            if actual_rate is not None and actual_rate < target_rate:
                # Slower than expected, apply multiplicative-decrease
                budget = utils.clamp(
                    self._config.sync_budget_min,
                    int(self._config.sync_budget_mul_dec * budget),
                    self._config.sync_budget_max,
                )
            else:
                # Faster than expected, apply additive-increase
                budget = utils.clamp(
                    self._config.sync_budget_min,
                    int(self._config.sync_budget_add_inc + budget),
                    self._config.sync_budget_max,
                )
            peer.sync_down_budget_size = int(budget)
        peer._sync_start_time = None
        self._sync_peers()

    def _try_add_peer(
        self,
        node_uuid: bytes,
        node_name: str,
        ip_address: str,
        zsub_port: int,
        zrouter_port: int,
    ) -> Optional[Peer]:
        """Try to add a Peer to the Swarm.

        Args:
            node_uuid: The byte-string UUID identifying the peer node (must not be the local node UUID).
            node_name: The unicode-string describing the peer node (must not be the local node name).
            ip_address: The unicode-string IP address the peer node uses for all network communication.
            zsub_port: The port number the peer node listens on for volatile connections.
            zrouter_port: The port number the peer node listens on for persistent connections.

        Returns: A Peer instance if one was added or already existed, else None.
        """
        zsub_endpoint = f"tcp://{ip_address}:{zsub_port}"
        zrouter_endpoint = f"tcp://{ip_address}:{zrouter_port}"
        old_peer = self._swarm.get_peer_by_uuid(node_uuid)
        if old_peer is not None:
            if (
                old_peer.node_name == node_name
                and old_peer._zsub_endpoint == zsub_endpoint
                and old_peer._zrouter_endpoint == zrouter_endpoint
            ):
                return old_peer

            logger.debug(f"Ignoring peer with clashing node UUID {node_name}")
            return None

        generation = 0
        old_peer = self._swarm.get_peer_by_name(node_name)
        if old_peer is not None:
            self._teardown_peer(old_peer)
            for zpub_sock in self._zpub_socks.values():
                zpub_sock.disconnect(old_peer._zsub_endpoint)
            self._swarm.remove_peer(old_peer)
            generation = old_peer.generation + 1
            logger.info(
                f"Usurping peer {node_name} at generation {old_peer.generation}"
            )

        peer = None
        try:
            for zpub_sock in self._zpub_socks.values():
                zpub_sock.connect(zsub_endpoint)
            zdealer_stream, zmonitor_stream = self._make_peer_streams()
            peer = Peer(
                node_uuid,
                node_name,
                generation,
                zsub_endpoint,
                zrouter_endpoint,
                zdealer_stream,
                zmonitor_stream,
            )
            self._setup_peer(peer)
        except zmq.ZMQError:
            # We should only get exceptions due to bad endpoint or config values
            # But once we successfully create a Peer, resets should be exception free
            logger.warning(f"Error adding peer {node_name}", exc_info=True)
            if peer is not None:
                self._teardown_peer(peer)
            for zpub_sock in self._zpub_socks.values():
                zpub_sock.disconnect(zsub_endpoint)
            return None

        self._swarm.add_peer(node_uuid, node_name, peer)
        logger.info(
            f"Added peer {node_name} at {ip_address}:{{{zsub_port},{zrouter_port}}}"
        )
        return peer

    def _make_peer_streams(self) -> Tuple[ZMQStream, ZMQStream]:
        """Make ZMQStreams for a Peer."""
        zdealer_stream = ZMQStream(self._zcontext.socket(zmq.DEALER), self._ioloop)
        zdealer_stream.setsockopt(zmq.LINGER, 0)
        zdealer_stream.setsockopt(zmq.TOS, self._config.persistent_ip_tos)
        zdealer_stream.setsockopt(zmq.RECONNECT_IVL, -1)
        zdealer_stream.setsockopt(
            zmq.CONNECT_TIMEOUT, int(self._config.persistent_tcp_maxrt * 1000)
        )
        zdealer_stream.setsockopt(
            zmq.TCP_MAXRT, int(self._config.persistent_tcp_maxrt * 1000)
        )
        zdealer_stream.setsockopt(zmq.IDENTITY, _to_zrouting_id(self._node_uuid))
        zmonitor_stream = ZMQStream(
            zdealer_stream.socket.get_monitor_socket(
                zmq.EVENT_CONNECTED | zmq.EVENT_DISCONNECTED
            ),
            self._ioloop,
        )
        zmonitor_stream.setsockopt(zmq.LINGER, 0)
        return zdealer_stream, zmonitor_stream

    def _setup_peer(self, peer: Peer) -> None:
        """Setup a Peer connection."""
        peer._zmonitor_stream.on_recv(
            functools.partial(self._handle_zmonitor_message, peer)
        )
        peer._zdealer_stream.on_recv(
            functools.partial(self._handle_zdealer_message, peer)
        )
        peer._zdealer_timeout = self._ioloop.call_later(
            self._config.persistent_tcp_maxrt,
            functools.partial(self._reset_peer, peer),
        )
        peer._zdealer_stream.connect(peer._zrouter_endpoint)

    def _teardown_peer(self, peer: Peer) -> None:
        """Teardown Peer connection."""
        peer._zdealer_tag = None
        if peer._zdealer_timeout is not None:
            self._ioloop.remove_timeout(peer._zdealer_timeout)
            peer._zdealer_timeout = None
        peer._zmonitor_stream.stop_on_recv()
        peer._zdealer_stream.stop_on_recv()
        peer._zdealer_stream.socket.disable_monitor()
        peer._zmonitor_stream.close()
        peer._zdealer_stream.close()

    def _reset_peer(self, peer: Peer) -> None:
        """Reset a Peer connection."""
        self._teardown_peer(peer)
        peer._zdealer_stream, peer._zmonitor_stream = self._make_peer_streams()
        self._setup_peer(peer)

    def _discover_peers(self) -> None:
        """Handle the on-going discovery process."""
        self._ioloop.call_later(
            utils.jitter(self._config.ping_period), self._discover_peers
        )

        now = self._clock()
        manifest = self._database.get_manifest()
        if self._history.try_add(now, manifest):
            logger.debug("Added a history entry")
        sync_lags = []
        for peer in self._swarm:
            peer_lag = now - self._history.find_most_recent_lte_tails(
                peer.manifest.tails
            )
            sync_lags.append(utils.SyncLag(peer.node_uuid, peer.manifest.seq, peer_lag))

        if self._beacon.try_send_ping(manifest, sync_lags):
            for peer in self._swarm:
                if peer._rtt_start_time is not None:
                    peer._rtt_deque.append((now, None))
                peer._rtt_start_time = now

        # Recalculate RTT stats for all peers
        for peer in self._swarm:
            while peer._rtt_deque:
                if (now - peer._rtt_deque[0][0]) > self._config.rtt_mean_window:
                    peer._rtt_deque.popleft()
                else:
                    break
            accum = 0
            hit = 0
            miss = 0
            for _, rtt in peer._rtt_deque:
                if rtt is None:
                    miss += 1
                else:
                    accum += rtt
                    hit += 1
            peer.rtt_mean_secs = 0.0 if hit == 0 else float(accum) / float(hit)
            peer.rtt_success_count = hit
            peer.rtt_failure_count = miss

    def _sync_peers(self) -> None:
        """Handle the on-going synchronisation process."""
        now = self._clock()
        manifest = self._database.get_manifest()
        for peer in self._swarm:
            if peer._zdealer_timeout is not None:
                # Peer is busy
                continue
            if self._overlay and peer.node_name not in self._overlay:
                # Peer is ineligible
                continue

            # Get updateable manifest tails sorted with the peer's own logs listed first.
            def key(node_uuid, item):
                return (0 if item[0] == node_uuid else 1) + random.random()

            updateable_tails = sorted(
                utils.iter_updateable(peer.manifest.tails, manifest.tails),
                key=functools.partial(key, peer.node_uuid),
            )

            if not updateable_tails:
                continue
            peer._sync_start_time = now
            self._send_zdealer_message(
                peer,
                _TAG_SYNC,
                self._compressor(
                    protocol.dumps_sync_request(
                        protocol.SyncRequest(
                            updateable_tails, peer.sync_down_budget_size
                        )
                    )
                ),
            )
            peer.send_sync_request_count += 1
            logger.debug(f"Sent sync request to {peer.node_name}")
