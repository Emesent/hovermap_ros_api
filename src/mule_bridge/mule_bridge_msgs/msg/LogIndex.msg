# Index in a log stored by a mule bridge process

# UUID of the source node (i.e. where the messages were originally published)
uint8[] node_uuid

# Log name
string log_name

# If trunc is true, then the log is always truncated to the latest message,
# else all messages are retained
bool trunc

# A byte index relative to the untruncated beginning of the log message data
uint64 index
