# Status of a peer known to a mule bridge process

# UUID and name identifiers for the peer node
uint8[] node_uuid
string node_name

# Generation of the peer node name, i.e. a count of previous claims to the same
# node name from different node UUIDs
uint32 generation

# Estimated mean round-trip-time to the peer over sliding window
float32 rtt_mean_secs

# Successful round-trip-time measurements to the peer over sliding window
uint32 rtt_success_count

# Unsuccessful round-trip-time measurements to the peer over sliding window
uint32 rtt_failure_count

# Local time at which the most recent manifest was received from the peer
time manifest_time

# Most recent manifest received from the peer
Manifest manifest

# Most recent verifiable local time at which the local database was a subset of
# the peer database, i.e. when all known logs were last 'fully uploaded' to the peer
time sync_up_time

# Most recent verifiable local time at which the peer database was a subset of
# the local database, i.e. when all known logs were last 'fully downloaded' from the peer
time sync_down_time

# Cumulative amount of data sent in sync replies to the peer
uint64 sync_up_size

# Cumulative amount of data received in sync replies from the peer
uint64 sync_down_size

# Cumulative amount of data used in sync replies from the peer
uint64 sync_down_used_size

# Current data budget specified in sync requests to the peer
uint64 sync_down_budget_size

# Cumulative protocol statistics
uint32 send_hello_request_count
uint32 recv_hello_request_count
uint32 send_hello_reply_count
uint32 recv_hello_reply_count
uint32 send_sync_request_count
uint32 recv_sync_request_count
uint32 send_sync_reply_count
uint32 recv_sync_reply_count
