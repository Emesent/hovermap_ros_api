# Status of a topic for which a mule bridge process has a publisher/subscriber

# Topic name
string topic_name

# Type name
string type_name

# Type md5sum
string type_md5sum

# Cumulative publisher/subscriber statistics
uint64 volatile_sub_msg_count
uint64 volatile_sub_raw_size
uint64 volatile_sub_bridged_size
uint64 volatile_pub_msg_count
uint64 volatile_pub_raw_size
uint64 volatile_pub_bridged_size
uint64 persistent_sub_msg_count
uint64 persistent_sub_raw_size
uint64 persistent_sub_bridged_size
uint64 persistent_pub_msg_count
uint64 persistent_pub_raw_size
uint64 persistent_pub_bridged_size
