# mule_bridge

## Overview

__mule_bridge__ provides statically-configured, transparent bridging of ROS
topics between independent ROS graphs (systems with different ROS masters). It
was developed to handle application-layer communication amongst the [Team CSIRO
Data61](https://research.csiro.au/robotics/our-work/darpa-subt-challenge-2018/)
robot fleet during the [SubT](https://www.subtchallenge.com/) challenge. The
nature of the challenge required a solution that could maximise the chances of
mission-critical data (collected by the robots) being communicated back to an
operator base station under harsh network conditions and time constraints. To
this end, our solution enabled transport of data in a hop-by-hop fashion, which
allowed messages to disseminate across the fleet without necessitating
end-to-end connectivity (i.e. we were able to exploit mobility such that any
robot could deliver data back to the operator on behalf of another robot).

## Features

__mule_bridge__ uses a peer-to-peer, disruption-tolerant communication model
designed for operation on top of a typical TCP/IP network stack. Peer discovery
and low-frequency metadata advertisements are handled by a 'beacon' which can
use either multicast UDP (in which case local network peers can be found
automatically) or unicast TCP (for peers with statically known addresses). ROS
topic data communication is handled exclusively via unicast TCP. Socket-options
and application-level heartbeats are used to keep TCP connections responsive
even in the face of unreliable network conditions.

__mule_bridge__ can transport the data of a particular ROS topic in either an
end-to-end or hop-by-hop fashion by configuring it for bridging under one of two
distinct QoS policies:
  1. volatile: direct, best-effort transport (useful for latency-sensitive data,
     e.g. status, commands)
  2. persistent: indirect, fully-reliable transport (useful for mission-critical
     data, e.g. maps, detections)

__mule_bridge__ implements volatile QoS by transporting individually-compressed
ROS message blobs over direct connections to peers. Through configuration, the
user can specify a mapping from local ROS topics to "volatile flows", each of
which uses its own dedicated queue/connection. This grouping can be used to
reduce transport overhead and tailor buffering behaviour per-flow. For incoming
data, remote ROS topics can be specified through configuration, and the
corresponding ROS message blobs will be delivered from peers that provide data
whenever there is direct connectivity.

__mule_bridge__ implements persistent QoS by storing ROS message blobs in a
local database and synchronising this database with peers. Through
configuration, the user can specify a mapping from local ROS topics to
"persistent logs", each of which forms an append-only log in the database using
a key based on the topic name and a UUID of the "owner" mule_bridge where the
messages were originally published. A log may be configured to use one of two
distinct storage policies:
1. trunc = False: retain every message from the beginning of the log, or
2. trunc = True: retain only the latest message of the log. Unlike volatile
data, persistent data is shared everywhere as part of the global database
synchronisation process. Remote ROS topics are still specified through
configuration, however that only determines whether or not incoming data that
has been stored in the database is also published to the local ROS system.

For the synchronisation process, each peer periodically sends out log metadata,
a.k.a. its "manifest" to the fleet. This metadata describes how much of each log
is locally stored, and thus available for synchronisation. When a peer manifest
describing newer log data becomes known, the bridge will request transfers of
data chunks from that peer until the local database has "caught-up". Each
transfer request nominates a "budget" that limits the maximum size of the
corresponding transfer reply. This budget is dynamically chosen to balance the
responsiveness and efficiency of transfers across a range of network conditions.
When assembling transfer replies, use of the budget is prioritised such that
data from locally sourced logs is transferred before data from other logs. Users
should be aware that this synchronisation process is "greedy" and possibly
inefficient unless they dynamically restrict the set of peers to which requests
may be sent. This feature is exposed via the ROS service "~set_overlay" (see
[SetOverlay.srv](mule_bridge_msgs/srv/SetOverlay.srv)).

__mule_bridge__ enables clients to monitor and make decisions around bridge
communication, by periodically publishing detailed status information to the
local ROS topic "~status" (see [Status.msg](mule_bridge_msgs/msg/Status.msg)).
This information includes details on local and remote manifests, which may be
useful to both operators and local ROS nodes. Additionally, the "~set_overlay"
service can be used to restrict outgoing requests to use a subset of possible
edges between peers (this subnetwork is called an overlay network). This may be
beneficial to large swarms, e.g. to restrict database synchronisation to take
place along edges of a minimum-spanning-tree of the network.

## Limitations

__mule_bridge__ is not intended for use in highly-reliable, dense networks
(where multicast or unacknowledged delivery would be more appropriate).
Additionally, it is not suitable for the transport of data with very low latency
requirements (e.g. millisecond), or for applications where local storage
capacity could be insufficient for holding the complete set of persistent data
bridged by the fleet over the course of the entire mission. Lastly, if users do
not impose any custom overlay networks, then they should be aware that
reconnection of long-lived network partitions via a "bottleneck" link may
exhibit poor performance due to the greedy synchronisation request strategy.

## To do

* Add option to throttle ROS publications and subscriptions.

## Configuration

__mule_bridge__ is fully configurable via ROS parameters under its private
namespace.

Below is an example yaml configuration that could be supplied via roslaunch.
Each subscription/publication item combines the given namespaces with the
topic_name to produce 1 or more subscribers/publishers. If namespaces is empty
or ommitted, just the topic_name is used.
```
# reusable aliases for namespaces
ROBOT: &robot ["r1"]
FLEET: &fleet ["r2", "r3", "r4"]

# network config (see config.py for all available parameters)
swarm_name: "$(arg fleet_name)"
node_name: "$(arg robot_name)"
ip_prefix: "192.168.2.0"
ip_netmask: "255.255.255.0"

# bridge config
#
# bridge.volatile.flows: a map of flows for outbound volatile communication
#   each flow MAY specify:
#   - ip_tos: the IP type-of-service mark
#   - sndhwm: the high-water-mark for the application send buffer
#   - sndbuf: the size for the underlying kernel transmit buffer (use with
#             caution)
#   each flow MUST specify:
#   - subscriptions: a list of local topic subscriptions for the flow
#       each item MUST include:
#       - topic: the base topic name (combined with namespaces if present)
#       - type: the message type name
#       each item MAY include:
#       - namespaces: a list of namespaces (1 subscription per combination)
#
# bridge.volatile.publications: a list of local topic publications for inbound
#                               volatile communication
#   each item MUST include:
#   - topic: the base topic name (combined with namespaces if present)
#   - type: the message type name
#   each item MAY include:
#   - namespaces: a list of namespaces that can prefix name
#
# bridge.persistent.logs: a map of logs for outbound persistent communication
#   each item MUST include:
#   - trunc: if true, only the latest message is stored instead of all messages
#   - subscriptions: a list of local topic subscriptions for the log
#       each item MUST include:
#       - topic: the base topic name (to be combined with namespaces if present)
#       - type: the message type name
#       each item MAY include:
#       - namespaces: a list of namespaces that can prefix name
#
# bridge.persistent.publications: a list of local topic publications for inbound
#                                 persistent communication
#   each item MUST include:
#   - topic: the base topic name (to be combined with namespaces if present)
#   - type: the message type name
#   each item MAY include:
#   - namespaces: a list of namespaces that can prefix name
bridge:
  volatile:
    flows:
      status:
        ip_tos: 0x30
        sndhwm: 1
        subscriptions:
          - topic: current_path
            type: nav_msgs/Path
            namespaces: *ROBOT
    publications:
      - topic: current_path
        type: nav_msgs/Path
        namespaces: *FLEET
  persistent:
    logs:
      core:
        trunc: False
        subscriptions:
          - topic: detections
            type: sensor_msgs/Image
            namespaces: *ROBOT
    publications:
      - topic: detections
        type: sensor_msgs/Image
        namespaces: *FLEET
```

## Alternatives

- [multimaster-fkie](http://wiki.ros.org/multimaster_fkie)
- [nimbro_network](https://github.com/AIS-Bonn/nimbro_network)
- [rosbridge_suite](http://wiki.ros.org/rosbridge_suite)
