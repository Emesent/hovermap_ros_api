from typing import Dict, List, NamedTuple, Optional

# IP type-of-service constants used in config defaults
IP_TOS_LOWDELAY_AND_PRIORITY = 0x30
IP_TOS_THROUGHPUT_AND_PRIORITY = 0x28
IP_TOS_THROUGHPUT = 0x08


class Config(NamedTuple):
    """A Config stores application settings and defines defaults."""

    class Bridge(NamedTuple):
        class Volatile(NamedTuple):
            class Flow(NamedTuple):
                class Subscription(NamedTuple):
                    topic: str
                    type: str
                    namespaces: Optional[List[str]] = None

                subscriptions: List[Subscription]
                ip_tos: int = IP_TOS_THROUGHPUT_AND_PRIORITY  # IP type-of-service
                sndhwm: int = 1000  # user-space send-queue high-water-mark
                sndbuf: int = -1  # kernel-space send-buffer size (use with caution)

            class Publication(NamedTuple):
                topic: str
                type: str
                namespaces: Optional[List[str]] = None

            flows: Dict[str, Flow] = {}
            publications: List[Publication] = []

        class Persistent(NamedTuple):
            class Log(NamedTuple):
                class Subscription(NamedTuple):
                    topic: str
                    type: str
                    namespaces: Optional[List[str]] = None

                trunc: bool  # truncate log storage
                subscriptions: List[Subscription]

            class Publication(NamedTuple):
                topic: str
                type: str
                namespaces: Optional[List[str]] = None

            logs: Dict[str, Log] = {}
            publications: List[Publication] = []

        volatile: Volatile
        persistent: Persistent

    # Bridge config
    bridge: Bridge

    # Swarm name shared amongst peers
    swarm_name: str = "swarm_1"

    # Unique name amongst peers
    node_name: str = "mule_1"

    # Duration of initial wait upon startup (e.g. for publishers/subscribers to connect)
    initial_wait: float = 5.0

    # IP network prefix for interface selection
    ip_prefix: str = "127.0.0.0"

    # IP network mask for interface selection
    ip_netmask: str = "255.255.255.0"

    # IP multicast group for ping traffic
    ping_mcast_group: str = "225.0.0.250"

    # IP addresses of unicast-only peers for ping traffic
    ping_ucast_addrs: List[str] = []

    # UDP port for ping traffic
    ping_port: int = 8123

    # Min of the port range to use for TCP connections
    min_port: int = 49152

    # Max of the port range to use for TCP connections
    max_port: int = 65535

    # Period for ping messages (units: seconds)
    ping_period: float = 5.0

    # Period for status publishing (units: seconds)
    status_period: float = 1.0

    # Window for round-trip-time mean calculation (units: second)
    rtt_mean_window: float = 60.0

    # Minimum resolution of manifest history (units: seconds)
    history_resolution: float = 5.0

    # IP type-of-service mark for ping traffic
    ping_ip_tos: int = IP_TOS_LOWDELAY_AND_PRIORITY

    # IP type-of-service mark for persistent traffic
    persistent_ip_tos: int = IP_TOS_THROUGHPUT

    # TCP maximum retransmission timeout for volatile traffic (units: seconds)
    volatile_tcp_maxrt: float = 10.0

    # TCP maximum retransmission timeout for persistent traffic (units: seconds)
    persistent_tcp_maxrt: float = 10.0

    # Volatile heartbeat interval (units: seconds)
    volatile_heartbeat_ivl: float = 10.0

    # Volatile heartbeat timeout (units: seconds)
    volatile_heartbeat_timeout: float = 60.0

    # Persistent heartbeat interval (units: seconds)
    persistent_heartbeat_ivl: float = 10.0

    # Persistent heartbeat timeout (units: seconds)
    persistent_heartbeat_timeout: float = 60.0

    # Timeout for exchanges (units: seconds)
    persistent_exchange_timeout: float = 60.0

    # Target duration for sync budget adjustment (units: seconds)
    sync_budget_target_duration: float = 10.0

    # Minimum size for sync budget adjustment (units: bytes)
    sync_budget_min: int = 1024 * 256

    # Maximum size for sync budget adjustment (units: bytes)
    sync_budget_max: int = 1024 * 1024 * 4

    # Additive-increase for sync budget adjustment (units: bytes)
    sync_budget_add_inc: int = 1024 * 256

    # Multiplicative-decrease for sync budget adjustment
    sync_budget_mul_dec: float = 0.5

    # Database can be memory-backed or file-backed
    database_memory: bool = False

    # Zlib compression level for transported topics
    # -1 for default, 0 to 9 for lowest to highest compression
    compression_level: int = -1
