"""Tests for newline-delimited JSON-RPC 2.0 framing (no subprocess)."""
import asyncio
import json
import pytest


def test_encode_request_is_newline_delimited_single_line():
    from agenticops.acp.jsonrpc import encode_message
    line = encode_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1                 # exactly one trailing newline
    assert b"\n" not in line[:-1]                  # no embedded newlines


def test_roundtrip_through_a_pipe():
    async def run():
        from agenticops.acp.jsonrpc import encode_message, read_message
        reader = asyncio.StreamReader()
        reader.feed_data(encode_message({"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}))
        reader.feed_data(encode_message({"jsonrpc": "2.0", "method": "session/update", "params": {"x": 1}}))
        reader.feed_eof()
        m1 = await read_message(reader)
        m2 = await read_message(reader)
        m3 = await read_message(reader)        # EOF -> None
        return m1, m2, m3
    m1, m2, m3 = asyncio.run(run())
    assert m1["id"] == 7 and m1["result"]["ok"] is True
    assert m2["method"] == "session/update"
    assert m3 is None


def test_read_skips_blank_and_nonjson_lines():
    async def run():
        from agenticops.acp.jsonrpc import encode_message, read_message
        reader = asyncio.StreamReader()
        reader.feed_data(b"\n")                              # blank
        reader.feed_data(b"not json at all\n")               # noise (e.g. stray stdout)
        reader.feed_data(encode_message({"jsonrpc": "2.0", "id": 1, "result": 1}))
        reader.feed_eof()
        return await read_message(reader)
    m = asyncio.run(run())
    assert m["id"] == 1
