import logging
import socket
import struct
import zlib
from typing import Callable, List, NamedTuple

from tornado.ioloop import IOLoop

from . import config, protocol, utils

logger = logging.getLogger(__name__)

_UDP_RECV_MAX = 65535


class PingCallbackArgs(NamedTuple):
    ip_address: str
    node_uuid: bytes
    node_name: str
    zsub_port: int
    zrouter_port: int
    manifest: utils.Manifest
    sync_lags: List[utils.SyncLag]


class PongCallbackArgs(NamedTuple):
    node_uuid: bytes


class Beacon:
    """
    A Beacon handles dynamic discovery of peer nodes via pings and pongs.

    UDP multicast is used to efficiently transmit ping messages to all Peers,
    without requiring them to be known ahead of time. UDP unicast can also be
    used to transmit ping messages to Peers over networks that don't support
    multicast. The ping payload contains information that peers can use to
    connect to this instance (if they are compatible and have use the same swarm
    name). It also carries manifest and synchronisation information.

    UDP unicast is used to transmit pong messages in response to pings. The pong
    message allows us to estimate the round-trip-time.
    """

    def __init__(
        self,
        config: config.Config,
        ioloop: IOLoop,
        node_uuid: bytes,
        ip_address: str,
        zsub_port: int,
        zrouter_port: int,
    ) -> None:
        self._config = config
        self._ioloop = ioloop

        self._node_uuid = node_uuid
        self._ip_address = ip_address
        self._zsub_port = zsub_port
        self._zrouter_port = zrouter_port

        self._ping_seq = 0
        self._ping_sock = None
        self._pong_sock = None

        self._ping_callback = None
        self._pong_callback = None

    def on_ping(
        self,
        callback: Callable[[PingCallbackArgs], None],
    ) -> None:
        """Set the ping callback."""
        self._ping_callback = callback

    def on_pong(self, callback: Callable[[PongCallbackArgs], None]) -> None:
        """Set the pong callback."""
        self._pong_callback = callback

    def try_send_ping(
        self, manifest: utils.Manifest, sync_lags: List[utils.SyncLag]
    ) -> bool:
        """Try to send a ping."""
        self._try_setup_ping_sock()
        self._try_setup_pong_sock()
        if self._ping_sock is None or self._pong_sock is None:
            return False

        # TODO(AP): consider Mill's algorithm for async RTT measurement
        self._ping_seq += 1
        pong_port = self._pong_sock.getsockname()[1]
        ping_frame = protocol.dumps_ping(
            protocol.Ping(
                self._ping_seq,
                self._config.swarm_name,
                self._config.node_name,
                self._node_uuid,
                pong_port,
                self._zsub_port,
                self._zrouter_port,
                manifest,
                sync_lags,
            )
        )

        # Be aware that if a manifest gets so large that the ping message size
        # exceeds the path MTU, fragments may be dropped, and performance may suffer
        if self._config.ping_mcast_group is not None:
            try:
                self._ping_sock.sendto(
                    ping_frame,
                    (self._config.ping_mcast_group, self._config.ping_port),
                )
            except socket.error:
                logger.warning("Error sending multicast ping", exc_info=True)
                self._teardown_ping_sock()
                return False

            logger.debug(
                f"Sent multicast ping to {self._config.ping_mcast_group}:{self._config.ping_port} via {self._ip_address}"
            )

        for ip_address in self._config.ping_ucast_addrs:
            if ip_address == self._ip_address:
                continue
            try:
                self._ping_sock.sendto(
                    ping_frame,
                    (ip_address, self._config.ping_port),
                )
            except socket.error:
                logger.warning("Error sending unicast ping", exc_info=True)
                self._teardown_ping_sock()
                return False

            logger.debug(
                f"Sent unicast ping to {ip_address}:{self._config.ping_port} via {self._ip_address}"
            )

        return True

    def _handle_ping(self, _fd, _events) -> None:
        """Receive a ping."""
        assert self._ping_sock, "Handler for ping called with no socket"

        try:
            ping_frame, (ip_address, _) = self._ping_sock.recvfrom(_UDP_RECV_MAX)
        except socket.error:
            logger.warning("Error receiving ping", exc_info=True)
            self._teardown_ping_sock()
            return

        try:
            ping = protocol.loads_ping(ping_frame)
        except (protocol.LoadError, zlib.error):
            logger.warning("Error loading ping", exc_info=True)
            return

        if ping.swarm_name != self._config.swarm_name:
            logger.debug(f"Ignored ping with swarm name {ping.swarm_name}")
            return

        if ping.node_uuid == self._node_uuid:
            logger.debug("Ignored ping with local node uuid")
            return

        if ping.node_name == self._config.node_name:
            logger.debug("Ignored ping with local node name")
            return

        self._try_send_pong(ping.ping_seq, ip_address, ping.pong_port)

        if self._ping_callback:
            self._ping_callback(
                PingCallbackArgs(
                    ip_address,
                    ping.node_uuid,
                    ping.node_name,
                    ping.zsub_port,
                    ping.zrouter_port,
                    ping.manifest,
                    ping.sync_lags,
                )
            )

    def _try_send_pong(self, ping_seq: int, ip_address: str, pong_port: int) -> bool:
        """Try to send a pong."""
        self._try_setup_pong_sock()
        if self._pong_sock is None:
            return False

        pong_frame = protocol.dumps_pong(protocol.Pong(ping_seq, self._node_uuid))
        try:
            self._pong_sock.sendto(pong_frame, (ip_address, pong_port))
        except socket.error:
            logger.warning("Error sending pong", exc_info=True)
            self._teardown_pong_sock()
            return False

        return True

    def _handle_pong(self, _fd, _events) -> None:
        """Receive a pong."""
        assert self._pong_sock, "Handler for pong called with no socket"

        try:
            frame, _ = self._pong_sock.recvfrom(65535)
        except socket.error:
            logger.warning("Error receiving pong", exc_info=True)
            self._teardown_pong_sock()
            return

        try:
            pong = protocol.loads_pong(frame)
        except protocol.LoadError:
            logger.warning("Error loading pong", exc_info=True)
            return

        if pong.ping_seq != self._ping_seq:
            logger.debug(f"Ignored pong with seq {pong.ping_seq}")
            return

        if self._pong_callback:
            self._pong_callback(PongCallbackArgs(pong.node_uuid))

    def _try_setup_ping_sock(self) -> bool:
        """Try setup the ping socket."""
        if self._ping_sock is not None:
            return True

        try:
            ping_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            ping_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            if self._config.ping_mcast_group is not None:
                # Send multicast pings to the local network only
                ping_sock.setsockopt(
                    socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("@i", 1)
                )

                # Send multicast pings using a specific interface
                ping_sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(self._ip_address),
                )

                # Register to receive multicast pings from specific group
                ping_sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_ADD_MEMBERSHIP,
                    socket.inet_aton(self._config.ping_mcast_group)
                    + socket.inet_aton(self._ip_address),
                )

            # Send pings with specific type-of-service mark
            ping_sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_TOS,
                struct.pack("@i", self._config.ping_ip_tos),
            )

            # Receive pings on specific port
            ping_sock.bind(("", self._config.ping_port))

        except socket.error:
            logger.warning("Error setting up ping socket", exc_info=True)
            return False

        self._ping_sock = ping_sock
        self._ioloop.add_handler(self._ping_sock, self._handle_ping, IOLoop.READ)
        return True

    def _teardown_ping_sock(self) -> None:
        """Teardown the ping socket."""
        if self._ping_sock is None:
            return

        self._ioloop.remove_handler(self._ping_sock)
        self._ping_sock = None

    def _try_setup_pong_sock(self) -> bool:
        """Try setup the pong socket."""
        if self._pong_sock is not None:
            return True

        try:
            pong_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Receive pongs on random port (allows for multimaster on a single host)
            pong_sock.bind(("", 0))

        except socket.error:
            logger.warning("Error setting up pong socket", exc_info=True)
            return False

        self._pong_sock = pong_sock
        self._ioloop.add_handler(self._pong_sock, self._handle_pong, IOLoop.READ)
        return True

    def _teardown_pong_sock(self) -> None:
        """Teardown the pong socket."""
        if self._pong_sock is None:
            return

        self._ioloop.remove_handler(self._pong_sock)
        self._pong_sock = None
