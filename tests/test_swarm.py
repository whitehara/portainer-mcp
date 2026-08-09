"""Unit tests for `src/portainer_mcp/swarm.py`."""

from __future__ import annotations

import json
import struct

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from portainer_mcp.redaction import SENTINEL
from portainer_mcp.swarm import (
    _infer_access_type,
    _merge_env,
    _scrub,
    _strip_docker_frames,
    register,
)

# ---------------------------------------------------------------------------
# _infer_access_type
# ---------------------------------------------------------------------------


def test_infer_access_type_agent():
    assert _infer_access_type("tcp://tasks.myservice:2375") == "agent"


def test_infer_access_type_docker_socket():
    assert _infer_access_type("unix:///var/run/docker.sock") == "docker-socket"


def test_infer_access_type_remote():
    assert _infer_access_type("tcp://192.168.0.10:2375") == "remote"


def test_infer_access_type_empty():
    assert _infer_access_type("") == "remote"


# ---------------------------------------------------------------------------
# _strip_docker_frames
# ---------------------------------------------------------------------------


def _make_frame(stream_type: int, payload: bytes) -> bytes:
    header = bytes([stream_type, 0, 0, 0]) + struct.pack(">I", len(payload))
    return header + payload


def test_strip_docker_frames_stdout():
    frame = _make_frame(1, b"hello world\n")
    assert _strip_docker_frames(frame) == "hello world\n"


def test_strip_docker_frames_stderr():
    frame = _make_frame(2, b"error line\n")
    assert _strip_docker_frames(frame) == "error line\n"


def test_strip_docker_frames_multiple():
    data = _make_frame(1, b"line1\n") + _make_frame(2, b"line2\n")
    assert _strip_docker_frames(data) == "line1\nline2\n"


def test_strip_docker_frames_tty_fallback():
    # Raw TTY output has no Docker framing — first byte is not 0/1/2.
    raw = b"raw tty output\n"
    assert _strip_docker_frames(raw) == "raw tty output\n"


def test_strip_docker_frames_empty():
    assert _strip_docker_frames(b"") == ""


# ---------------------------------------------------------------------------
# Tool registration — happy path via mock transport
# ---------------------------------------------------------------------------


def _make_mock_client(
    routes: dict[str, object], captured: list[httpx.Request] | None = None
) -> httpx.AsyncClient:
    """Build an AsyncClient backed by a dict of path → response.

    Route keys may be prefixed with an HTTP method and a space (e.g.
    "GET /stacks/10") to give GET/PUT on the same path different canned
    responses; unprefixed keys match any method, as most existing routes
    do. Pass `captured` to record every request the client makes, so a
    test can assert on the body a PUT actually sent.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        path = request.url.path
        # Strip the leading /api prefix that the real client's base_url adds.
        key = path.removeprefix("/api")
        # Check params too for services?status=true
        full = key + ("?" + str(request.url.params) if request.url.params else "")
        method = request.method
        for candidate in (f"{method} {full}", f"{method} {key}", full, key):
            if candidate in routes:
                body = routes[candidate]
                break
        else:
            return httpx.Response(404, json={"message": f"not found: {key}"})
        if isinstance(body, httpx.Response):
            return body
        if isinstance(body, (dict, list)):
            return httpx.Response(200, json=body)
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://test/api")


@pytest.fixture()
def mcp_with_swarm():
    mcp = FastMCP(name="test")
    client = _make_mock_client(
        {
            "/endpoints": [
                {"Id": 1, "Name": "swarm-env", "URL": "tcp://tasks.agent:2375"},
                {"Id": 2, "Name": "standalone", "URL": "tcp://192.168.0.5:2375"},
            ],
            "/endpoints/1/docker/swarm": {"ID": "abc123", "CreatedAt": "2024-01-01", "UpdatedAt": "2024-01-02"},
            "/endpoints/2/docker/swarm": httpx.Response(404),  # not a swarm env
            "/endpoints/1/docker/nodes": [
                {
                    "ID": "node1",
                    "Description": {
                        "Hostname": "host1",
                        "Resources": {"NanoCPUs": 4_000_000_000, "MemoryBytes": 8_000_000_000},
                    },
                    "Spec": {"Role": "Manager", "Availability": "Active"},
                    "Status": {"State": "ready", "Addr": "192.168.0.1"},
                }
            ],
            "/endpoints/1/docker/services?status=true": [
                {
                    "ID": "svc1",
                    "Spec": {
                        "Name": "mystack_web",
                        "Labels": {"com.docker.stack.namespace": "mystack"},
                        "TaskTemplate": {
                            "ContainerSpec": {"Image": "nginx:latest"},
                            "Placement": {"Constraints": ["node.role==manager"]},
                        },
                        "Mode": {"Replicated": {"Replicas": 2}},
                        "EndpointSpec": {"Ports": []},
                        "Networks": [],
                    },
                    "ServiceStatus": {"RunningTasks": 1, "DesiredTasks": 2},
                    "CreatedAt": "2024-01-01",
                    "UpdatedAt": "2024-01-02",
                }
            ],
            "/endpoints/1/docker/tasks": [
                {
                    "ID": "task1",
                    "ServiceID": "svc1",
                    "NodeID": "node1",
                    "DesiredState": "running",
                    "Status": {
                        "State": "running",
                        "Timestamp": "2024-01-01",
                        "Err": "",
                        "ContainerStatus": {"ContainerID": "ctr1"},
                    },
                }
            ],
            "/endpoints/1/docker/containers/ctr1/logs": _make_frame(1, b"log line\n"),
            "/stacks": [
                {"Id": 10, "Name": "mystack", "Type": 1, "EndpointId": 1},
                {"Id": 11, "Name": "compose-stack", "Type": 2, "EndpointId": 1},
            ],
        }
    )
    register(mcp, client, read_only=False)
    return mcp


@pytest.mark.asyncio
async def test_list_swarm_environments(mcp_with_swarm):
    result = await mcp_with_swarm.call_tool("listSwarmEnvironments", {})
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["environmentId"] == 1
    assert data[0]["swarmId"] == "abc123"
    assert data[0]["accessType"] == "agent"


@pytest.mark.asyncio
async def test_list_swarm_nodes(mcp_with_swarm):
    result = await mcp_with_swarm.call_tool("listSwarmNodes", {"environment_id": 1})
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["hostname"] == "host1"
    assert data[0]["role"] == "manager"
    assert data[0]["cpus"] == 4


@pytest.mark.asyncio
async def test_list_swarm_services(mcp_with_swarm):
    result = await mcp_with_swarm.call_tool("listSwarmServices", {"environment_id": 1})
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["name"] == "mystack_web"
    assert data[0]["replicas"] == {"desired": 2, "running": 1}


@pytest.mark.asyncio
async def test_list_swarm_services_filter_stack(mcp_with_swarm):
    result = await mcp_with_swarm.call_tool(
        "listSwarmServices", {"environment_id": 1, "stack_name": "other"}
    )
    data = json.loads(result.content[0].text)
    assert data == []


@pytest.mark.asyncio
async def test_list_swarm_tasks(mcp_with_swarm):
    result = await mcp_with_swarm.call_tool("listSwarmTasks", {"environment_id": 1})
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["state"] == "running"
    assert data[0]["containerId"] == "ctr1"


@pytest.mark.asyncio
async def test_get_swarm_info(mcp_with_swarm):
    result = await mcp_with_swarm.call_tool("getSwarmInfo", {"environment_id": 1})
    data = json.loads(result.content[0].text)
    assert data["id"] == "abc123"
    assert data["managerCount"] == 1
    assert data["workerCount"] == 0
    assert data["serviceCount"] == 1
    assert data["stackCount"] == 1  # only Type==1 swarm stacks


@pytest.mark.asyncio
async def test_get_swarm_service_logs(mcp_with_swarm):
    result = await mcp_with_swarm.call_tool(
        "getSwarmServiceLogs",
        {"environment_id": 1, "service_name": "mystack_web"},
    )
    assert result.content[0].text == "log line\n"


@pytest.mark.asyncio
async def test_get_swarm_service_logs_no_running_task():
    mcp = FastMCP(name="test")
    client = _make_mock_client(
        {
            "/endpoints/1/docker/tasks": [],
        }
    )
    register(mcp, client, read_only=False)
    result = await mcp.call_tool(
        "getSwarmServiceLogs",
        {"environment_id": 1, "service_name": "ghost_svc"},
    )
    assert "no running task found" in result.content[0].text


@pytest.mark.asyncio
async def test_create_swarm_stack(mcp_with_swarm):
    mcp = FastMCP(name="test")
    client = _make_mock_client(
        {
            "/endpoints/1/docker/swarm": {"ID": "abc123"},
            "/stacks/create/swarm/string": {"Id": 42, "Name": "newstack"},
        }
    )
    register(mcp, client, read_only=False)
    result = await mcp.call_tool(
        "createSwarmStack",
        {
            "environment_id": 1,
            "name": "newstack",
            "compose_file": "version: '3'\nservices:\n  web:\n    image: nginx\n",
        },
    )
    data = json.loads(result.content[0].text)
    assert data["id"] == 42
    assert data["name"] == "newstack"


@pytest.mark.asyncio
async def test_create_swarm_stack_read_only():
    mcp = FastMCP(name="test")
    client = _make_mock_client({})
    register(mcp, client, read_only=True)
    with pytest.raises(ToolError, match="read-only"):
        await mcp.call_tool(
            "createSwarmStack",
            {"environment_id": 1, "name": "x", "compose_file": "version: '3'"},
        )


# ---------------------------------------------------------------------------
# updateSwarmStack — env diff-merge
# ---------------------------------------------------------------------------

_STACK_10_ENV = [
    {"name": "A", "value": "s3cr3t-alpha"},
    {"name": "B", "value": "s3cr3t-bravo"},
]
_STACK_10_COMPOSE = "version: '3'\nservices:\n  web:\n    image: nginx:1.24\n"


def _stack_routes(**overrides) -> dict[str, object]:
    stack = {
        "Id": 10,
        "Name": "mystack",
        "Type": 1,
        "GitConfig": None,
        "Env": _STACK_10_ENV,
    }
    stack.update(overrides)
    # The mock PUT response doesn't echo the request body (it's a static
    # fixture, not a real server), so it omits "Env" to force
    # update_swarm_stack's fallback path — reporting env_names from the
    # merged env it computed and sent, not from a stale canned response.
    put_response = {k: v for k, v in stack.items() if k != "Env"}
    return {
        "GET /stacks/10": stack,
        "PUT /stacks/10": put_response,
        "GET /stacks/10/file": {"StackFileContent": _STACK_10_COMPOSE},
        "GET /stacks/12": {
            "Id": 12,
            "Name": "gitstack",
            "Type": 1,
            "GitConfig": {"URL": "https://example.invalid/repo.git"},
            "Env": [],
        },
        "PUT /stacks/12": {"Id": 12, "Name": "gitstack", "Env": []},
        "GET /stacks/13": {"Id": 13, "Name": "k8sstack", "Type": 3, "Env": None},
    }


def _put_body(captured: list[httpx.Request], path: str = "/api/stacks/10") -> dict:
    for req in captured:
        if req.method == "PUT" and req.url.path == path:
            return json.loads(req.content)
    raise AssertionError(f"no PUT to {path} captured")


@pytest.mark.asyncio
async def test_merge_env_preserves_when_omitted():
    mcp = FastMCP(name="test")
    captured: list[httpx.Request] = []
    client = _make_mock_client(_stack_routes(), captured=captured)
    register(mcp, client, read_only=False)
    result = await mcp.call_tool(
        "updateSwarmStack", {"stack_id": 10, "environment_id": 1}
    )
    data = json.loads(result.content[0].text)
    assert data["updated"] is True
    assert set(data["env_names"]) == {"A", "B"}
    body = _put_body(captured)
    assert body["env"] == _STACK_10_ENV
    assert body["stackFileContent"] == _STACK_10_COMPOSE


@pytest.mark.asyncio
async def test_merge_env_set_upsert():
    mcp = FastMCP(name="test")
    captured: list[httpx.Request] = []
    client = _make_mock_client(_stack_routes(), captured=captured)
    register(mcp, client, read_only=False)
    result = await mcp.call_tool(
        "updateSwarmStack",
        {
            "stack_id": 10,
            "environment_id": 1,
            "env_set": {"A": "s3cr3t-alpha-2", "C": "s3cr3t-charlie"},
        },
    )
    data = json.loads(result.content[0].text)
    assert set(data["env_names"]) == {"A", "B", "C"}
    body = _put_body(captured)
    by_name = {p["name"]: p["value"] for p in body["env"]}
    assert by_name == {
        "A": "s3cr3t-alpha-2",
        "B": "s3cr3t-bravo",
        "C": "s3cr3t-charlie",
    }


@pytest.mark.asyncio
async def test_merge_env_unset():
    mcp = FastMCP(name="test")
    captured: list[httpx.Request] = []
    client = _make_mock_client(_stack_routes(), captured=captured)
    register(mcp, client, read_only=False)
    result = await mcp.call_tool(
        "updateSwarmStack",
        {"stack_id": 10, "environment_id": 1, "env_unset": ["A", "nope"]},
    )
    data = json.loads(result.content[0].text)
    assert data["env_names"] == ["B"]
    assert data["env_removed"] == ["A"]
    body = _put_body(captured)
    assert body["env"] == [{"name": "B", "value": "s3cr3t-bravo"}]


@pytest.mark.asyncio
async def test_merge_env_replace_empty_wipes():
    mcp = FastMCP(name="test")
    captured: list[httpx.Request] = []
    client = _make_mock_client(_stack_routes(), captured=captured)
    register(mcp, client, read_only=False)
    result = await mcp.call_tool(
        "updateSwarmStack",
        {"stack_id": 10, "environment_id": 1, "env_replace": []},
    )
    data = json.loads(result.content[0].text)
    assert data["env_names"] == []
    body = _put_body(captured)
    assert body["env"] == []


@pytest.mark.asyncio
async def test_merge_env_replace_conflicts_with_set():
    mcp = FastMCP(name="test")
    client = _make_mock_client(_stack_routes())
    register(mcp, client, read_only=False)
    with pytest.raises(ToolError, match="env_replace"):
        await mcp.call_tool(
            "updateSwarmStack",
            {
                "stack_id": 10,
                "environment_id": 1,
                "env_replace": [],
                "env_set": {"A": "x"},
            },
        )


def test_merge_env_dedupes_duplicate_names():
    current = [
        {"name": "A", "value": "first"},
        {"name": "A", "value": "second"},
    ]
    merged, summary = _merge_env(current, None, None)
    assert merged == [{"name": "A", "value": "second"}]
    assert summary["deduped"] == ["A"]


def test_merge_env_accepts_capitalized_pair_keys():
    current = [{"Name": "A", "Value": "v1"}]
    merged, summary = _merge_env(current, {"B": "v2"}, None)
    assert merged == [{"name": "A", "value": "v1"}, {"name": "B", "value": "v2"}]
    assert summary["added"] == ["B"]


@pytest.mark.asyncio
async def test_update_keeps_compose_file_when_omitted():
    mcp = FastMCP(name="test")
    captured: list[httpx.Request] = []
    client = _make_mock_client(_stack_routes(), captured=captured)
    register(mcp, client, read_only=False)
    await mcp.call_tool("updateSwarmStack", {"stack_id": 10, "environment_id": 1})
    body = _put_body(captured)
    assert body["stackFileContent"] == _STACK_10_COMPOSE


@pytest.mark.asyncio
async def test_update_rejects_git_backed_stack():
    mcp = FastMCP(name="test")
    client = _make_mock_client(_stack_routes())
    register(mcp, client, read_only=False)
    with pytest.raises(ToolError, match="[Gg]it"):
        await mcp.call_tool(
            "updateSwarmStack",
            {
                "stack_id": 12,
                "environment_id": 1,
                "compose_file": "version: '3'",
            },
        )


@pytest.mark.asyncio
async def test_update_rejects_kubernetes_stack():
    mcp = FastMCP(name="test")
    client = _make_mock_client(_stack_routes())
    register(mcp, client, read_only=False)
    with pytest.raises(ToolError, match="Swarm"):
        await mcp.call_tool(
            "updateSwarmStack",
            {
                "stack_id": 13,
                "environment_id": 1,
                "compose_file": "version: '3'",
            },
        )


@pytest.mark.asyncio
async def test_update_response_contains_no_env_values():
    mcp = FastMCP(name="test")
    client = _make_mock_client(_stack_routes())
    register(mcp, client, read_only=False)
    result = await mcp.call_tool(
        "updateSwarmStack", {"stack_id": 10, "environment_id": 1}
    )
    text = result.content[0].text
    assert "s3cr3t-alpha" not in text
    assert "s3cr3t-bravo" not in text


@pytest.mark.asyncio
async def test_error_body_scrubbed():
    mcp = FastMCP(name="test")
    routes = _stack_routes()
    routes["PUT /stacks/10"] = httpx.Response(
        400,
        json={"message": "invalid payload", "env": _STACK_10_ENV},
    )
    client = _make_mock_client(routes)
    register(mcp, client, read_only=False)
    with pytest.raises(ToolError) as exc_info:
        await mcp.call_tool(
            "updateSwarmStack", {"stack_id": 10, "environment_id": 1}
        )
    assert "s3cr3t-alpha" not in str(exc_info.value)
    assert "s3cr3t-bravo" not in str(exc_info.value)


def test_error_body_scrub_across_500_char_boundary():
    secret = "s3cr3t-boundary-value-0123456789"
    padding = "x" * 490
    text = padding + secret + "y" * 50  # secret straddles the 500-char cutoff
    scrubbed = _scrub(text, {secret})
    assert secret not in scrubbed
    assert "[REDACTED]" in scrubbed
    # If truncation ran before scrubbing, only a prefix of `secret` would
    # have survived into the 500-char text and wouldn't match for
    # replacement — assert no such orphaned prefix leaks through.
    for cut in range(4, len(secret)):
        assert secret[:cut] not in scrubbed


@pytest.mark.asyncio
async def test_update_rejects_sentinel_in_env_set():
    mcp = FastMCP(name="test")
    client = _make_mock_client(_stack_routes())
    register(mcp, client, read_only=False)
    with pytest.raises(ToolError, match="REDACTED"):
        await mcp.call_tool(
            "updateSwarmStack",
            {
                "stack_id": 10,
                "environment_id": 1,
                "env_set": {"A": SENTINEL},
            },
        )


@pytest.mark.asyncio
async def test_update_allows_sentinel_when_expose_enabled(monkeypatch):
    monkeypatch.setenv("PORTAINER_EXPOSE_ENV_VALUES", "1")
    mcp = FastMCP(name="test")
    captured: list[httpx.Request] = []
    client = _make_mock_client(_stack_routes(), captured=captured)
    register(mcp, client, read_only=False)
    result = await mcp.call_tool(
        "updateSwarmStack",
        {
            "stack_id": 10,
            "environment_id": 1,
            "env_set": {"A": SENTINEL},
        },
    )
    data = json.loads(result.content[0].text)
    assert data["updated"] is True
    body = _put_body(captured)
    by_name = {p["name"]: p["value"] for p in body["env"]}
    assert by_name["A"] == SENTINEL


@pytest.mark.asyncio
async def test_update_swarm_stack_read_only():
    mcp = FastMCP(name="test")
    client = _make_mock_client({})
    register(mcp, client, read_only=True)
    with pytest.raises(ToolError, match="read-only"):
        await mcp.call_tool(
            "updateSwarmStack",
            {"stack_id": 10, "environment_id": 1, "compose_file": "version: '3'"},
        )
