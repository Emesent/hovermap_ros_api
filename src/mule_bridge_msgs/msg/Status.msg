# Status of a mule bridge process

# Swarm name used by the local node and its peers
string swarm_name

# UUID and name identifiers of the local node
uint8[] node_uuid
string node_name

# Peers
Peer[] peers

# Topics
Topic[] topics

# Most recent manifest
Manifest manifest

# Local time at which the most recent was generated
time manifest_time
