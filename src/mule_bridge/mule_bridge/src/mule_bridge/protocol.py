import io
from typing import List, NamedTuple, Type, TypeVar, cast

import avro.errors
import avro.io
import avro.name
import avro.schema
import avro.utils

from . import utils

_AVSC_JSON = [
    {
        "name": "LogIndex",
        "type": "record",
        "fields": [
            {"name": "node_uuid", "type": "bytes"},
            {"name": "log_name", "type": "string"},
            {"name": "trunc", "type": "boolean"},
            {"name": "index", "type": "int"},
        ],
    },
    {
        "name": "LogChunk",
        "type": "record",
        "fields": [
            {"name": "head", "type": "LogIndex"},
            {
                "name": "blobs",
                "type": {"type": "array", "items": "bytes"},
            },
        ],
    },
    {
        "name": "SyncLag",
        "type": "record",
        "fields": [
            {"name": "node_uuid", "type": "bytes"},
            {"name": "manifest_seq", "type": "int"},
            {"name": "lag", "type": "float"},
        ],
    },
    {
        "name": "Ping",
        "type": "record",
        "fields": [
            {"name": "ping_seq", "type": "int"},
            {"name": "swarm_name", "type": "string"},
            {"name": "node_name", "type": "string"},
            {"name": "node_uuid", "type": "bytes"},
            {"name": "pong_port", "type": "int"},
            {"name": "zsub_port", "type": "int"},
            {"name": "zrouter_port", "type": "int"},
            {
                "name": "manifest",
                "type": {
                    "name": "Manifest",
                    "type": "record",
                    "fields": [
                        {"name": "seq", "type": "int"},
                        {
                            "name": "tails",
                            "type": {"type": "array", "items": "LogIndex"},
                        },
                    ],
                },
            },
            {
                "name": "sync_lags",
                "type": {"type": "array", "items": "SyncLag"},
            },
        ],
    },
    {
        "name": "Pong",
        "type": "record",
        "fields": [
            {"name": "ping_seq", "type": "int"},
            {"name": "node_uuid", "type": "bytes"},
        ],
    },
    {
        "name": "HelloRequest",
        "type": "record",
        "fields": [
            {"name": "node_name", "type": "string"},
            {"name": "ip_address", "type": "string"},
            {"name": "zsub_port", "type": "int"},
            {"name": "zrouter_port", "type": "int"},
        ],
    },
    {
        "name": "HelloReply",
        "type": "record",
        "fields": [],
    },
    {
        "name": "SyncRequest",
        "type": "record",
        "fields": [
            {
                "name": "tails",
                "type": {"type": "array", "items": "LogIndex"},
            },
            {"name": "budget", "type": "int"},
        ],
    },
    {
        "name": "SyncReply",
        "type": "record",
        "fields": [
            {
                "name": "updates",
                "type": {"type": "array", "items": "LogChunk"},
            }
        ],
    },
]


_AVSC_NAMES = avro.name.Names()
_AVSC_OBJ = avro.schema.make_avsc_object(_AVSC_JSON, _AVSC_NAMES)


T = TypeVar("T")


class Ping(NamedTuple):
    """Struct for protocol data."""

    ping_seq: int
    swarm_name: str
    node_name: str
    node_uuid: bytes
    pong_port: int
    zsub_port: int
    zrouter_port: int
    manifest: utils.Manifest
    sync_lags: List[utils.SyncLag]


class Pong(NamedTuple):
    """Typed struct for equivalent protocol message."""

    ping_seq: int
    node_uuid: bytes


class HelloRequest(NamedTuple):
    """Typed struct for equivalent protocol message."""

    node_name: str
    ip_address: str
    zsub_port: int
    zrouter_port: int


class HelloReply(NamedTuple):
    """Typed struct for equivalent protocol message."""


class SyncRequest(NamedTuple):
    """Typed struct for equivalent protocol message."""

    tails: List[utils.LogIndex]
    budget: int


class SyncReply(NamedTuple):
    """Typed struct for equivalent protocol message."""

    updates: List[utils.LogChunk]


class LoadError(Exception):
    """Exception class for errors encountered during deserialisation."""


def _get_schema(name: str) -> avro.schema.NamedSchema:
    """Fetch a loaded avro schema by name."""
    schema = _AVSC_NAMES.get_name(name)
    assert schema, "Bad schema name"
    return schema


def _loads_helper(cls, obj):
    """Recursively load an object read with avro into a class/type."""
    # types enforced by avro, we handle NamedTuple creation from dict
    if hasattr(cls, "__annotations__"):
        return cls(
            **{k: _loads_helper(v, obj[k]) for k, v in cls.__annotations__.items()}
        )
    elif hasattr(cls, "__origin__"):
        if cls.__origin__ == list:
            # typing.List[X]
            return [_loads_helper(cls.__args__[0], x) for x in obj]
        else:
            assert False, f"Unsupported type annotation: {cls.__origin__}"
    else:
        return obj


def _dumps_helper(cls, obj):
    """Recursively dump an object into a form that can be written with avro."""
    # types enforced by avro, we handle dict creation from NamedTuple
    if hasattr(cls, "__annotations__"):
        return {
            k: _dumps_helper(v, getattr(obj, k)) for k, v in obj.__annotations__.items()
        }
    elif hasattr(cls, "__origin__"):
        if cls.__origin__ == list:
            return [_dumps_helper(cls.__args__[0], x) for x in obj]
        elif cls.__origin__ == dict:
            return {
                _dumps_helper(cls.__args__[0], k): _dumps_helper(cls.__args__[1], v)
                for k, v in obj.items()
            }
        else:
            assert False, f"Unsupported type annotation: {cls.__origin__}"
    else:
        return obj


def _loads(schema: avro.schema.Schema, cls: Type[T], frame: bytes) -> T:
    """Load a frame using a schema."""
    try:
        reader = avro.io.DatumReader(schema, schema)
        buf = io.BytesIO(frame)
        decoder = avro.io.BinaryDecoder(buf)
        return cast(cls, _loads_helper(cls, reader.read(decoder)))
    except avro.errors.AvroException as ex:
        raise LoadError(ex)


def _dumps(schema: avro.schema.Schema, obj: NamedTuple) -> bytes:
    """Dump an object using a schema."""
    buf = io.BytesIO()
    encoder = avro.io.BinaryEncoder(buf)
    writer = avro.io.DatumWriter(schema)
    writer.write(_dumps_helper(type(obj), obj), encoder)
    buf.seek(0)
    return buf.read()


def dumps_ping(ping: Ping) -> bytes:
    """Serialise a ping message."""
    return _dumps(_get_schema("Ping"), ping)


def loads_ping(frame: bytes) -> Ping:
    """Deserialise a ping message."""
    return _loads(_get_schema("Ping"), Ping, frame)


def dumps_pong(pong: Pong) -> bytes:
    """Serialise a pong message."""
    return _dumps(_get_schema("Pong"), pong)


def loads_pong(frame: bytes) -> Pong:
    """Deserialise a pong message."""
    return _loads(_get_schema("Pong"), Pong, frame)


def dumps_hello_request(hello_request: HelloRequest) -> bytes:
    """Serialise a hello request message."""
    return _dumps(_get_schema("HelloRequest"), hello_request)


def loads_hello_request(frame: bytes) -> HelloRequest:
    """Deserialise a hello request message."""
    return _loads(_get_schema("HelloRequest"), HelloRequest, frame)


def dumps_hello_reply(hello_reply: HelloReply) -> bytes:
    """Serialise a hello reply message."""
    return _dumps(_get_schema("HelloReply"), hello_reply)


def loads_hello_reply(frame: bytes) -> HelloReply:
    """Deserialise a hello reply message."""
    return _loads(_get_schema("HelloReply"), HelloReply, frame)


def dumps_sync_request(sync_request: SyncRequest) -> bytes:
    """Serialise a sync request message."""
    return _dumps(_get_schema("SyncRequest"), sync_request)


def loads_sync_request(frame) -> SyncRequest:
    """Deserialise a sync request message."""
    return _loads(_get_schema("SyncRequest"), SyncRequest, frame)


def dumps_sync_reply(sync_reply: SyncReply) -> bytes:
    """Serialise a sync reply message."""
    return _dumps(_get_schema("SyncReply"), sync_reply)


def loads_sync_reply(frame: bytes) -> SyncReply:
    """Deserialise a sync reply message."""
    return _loads(_get_schema("SyncReply"), SyncReply, frame)
