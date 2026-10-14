"""Versioned host-device protocol (binary, integrity-checked)."""
from __future__ import annotations

import struct
import zlib

VERSION = 1
HELLO, CONFIGURE, RUN_TEST, RESULT, ERROR = 1, 2, 3, 4, 255
HEADER = struct.Struct("<BBHIH")  # version, type, seq, len, crc16
MAX_PAYLOAD = 4096  # inference vectors are small; cap to reject garbage lengths


def crc16(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFF


def encode(mtype: int, seq: int, payload: bytes = b"") -> bytes:
    return HEADER.pack(VERSION, mtype, seq, len(payload), crc16(payload)) + payload


def decode(buf: bytes) -> tuple[int, int, bytes]:
    if len(buf) < HEADER.size:
        raise ValueError("short header")
    ver, mtype, seq, ln, crc = HEADER.unpack(buf[:HEADER.size])
    if ver != VERSION:
        raise ValueError(f"protocol version {ver} != {VERSION}")
    if ln > MAX_PAYLOAD:
        raise ValueError(f"payload length {ln} exceeds cap {MAX_PAYLOAD}")
    body = buf[HEADER.size:HEADER.size + ln]
    if len(body) != ln:
        raise ValueError("short payload")
    if crc16(body) != crc:
        raise ValueError("crc mismatch — rejecting message")
    return mtype, seq, body


def decode_stream(buf: bytes) -> tuple[list[tuple[int, int, bytes]], bytes]:
    """Deframe a byte stream into complete messages.

    Returns (messages, leftover). Trailing incomplete bytes are returned as
    leftover (caller buffers them); they are never silently dropped.
    """
    msgs: list[tuple[int, int, bytes]] = []
    off = 0
    while len(buf) - off >= HEADER.size:
        ver, mtype, seq, ln, crc = HEADER.unpack(buf[off:off + HEADER.size])
        if ver != VERSION:
            raise ValueError(f"protocol version {ver} != {VERSION} at offset {off}")
        if ln > MAX_PAYLOAD:
            raise ValueError(f"payload length {ln} exceeds cap at offset {off}")
        if len(buf) - off - HEADER.size < ln:
            break  # incomplete payload: wait for more bytes
        body = buf[off + HEADER.size:off + HEADER.size + ln]
        if crc16(body) != crc:
            raise ValueError(f"crc mismatch at offset {off} — rejecting message")
        msgs.append((mtype, seq, body))
        off += HEADER.size + ln
    return msgs, buf[off:]


def check_seq(msgs: list[tuple[int, int, bytes]], start: int = 0) -> None:
    """Reject gaps/replays in a sequence-numbered run. Raises on mismatch."""
    want = start
    for _, seq, _ in msgs:
        if seq != want:
            raise ValueError(f"sequence break: got {seq}, want {want}")
        want = (want + 1) & 0xFFFF
