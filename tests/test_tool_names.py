"""Regression test: every tool name `build_server()` exposes stays within
Cloudflare's 40-char tool name limit.

`PORTAINER_PROFILES=ALL` disables the tag filter so this covers every
OpenAPI-generated tool the bundled spec can produce, not just the
default profile set — a future spec bump (new operationId, renamed
operation) must fail this test rather than silently ship a name
Cloudflare rejects.
"""

from __future__ import annotations

import asyncio

from portainer_mcp.server import build_server

MAX_TOOL_NAME_LENGTH = 40


def test_all_tool_names_within_cloudflare_limit(monkeypatch):
    # Plain `def`, not `async def`: build_server() manages its own event
    # loop internally (asyncio.run() in its startup select-coverage check),
    # so it must be called outside of pytest-asyncio's loop, not inside it.
    monkeypatch.setenv("PORTAINER_URL", "http://test")
    monkeypatch.setenv("PORTAINER_API_KEY", "test-key")
    monkeypatch.setenv("PORTAINER_PROFILES", "ALL")

    mcp = build_server()
    tools = asyncio.run(mcp.list_tools())

    too_long = [t.name for t in tools if len(t.name) > MAX_TOOL_NAME_LENGTH]
    assert not too_long, (
        f"{len(too_long)} tool name(s) exceed {MAX_TOOL_NAME_LENGTH} chars: "
        f"{too_long} — add a _TOOL_NAME_REMAP entry in server.py"
    )
