"""Docker Swarm inspection and management tools for Portainer MCP."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

logger = logging.getLogger("portainer_mcp")

_STACK_TYPE_SWARM = 1


def _infer_access_type(url: str) -> str:
    if "tasks." in url:
        return "agent"
    if "docker.sock" in url:
        return "docker-socket"
    return "remote"


def _strip_docker_frames(data: bytes) -> str:
    """Strip Docker log-multiplexing 8-byte frame headers.

    Falls back to raw UTF-8 decode for TTY-attached containers that emit
    plain bytes without framing.
    """
    result = []
    offset = 0
    while offset + 8 <= len(data):
        stream_type = data[offset]
        if stream_type not in (0, 1, 2):
            return data.decode("utf-8", errors="replace")
        size = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        offset += 8
        result.append(data[offset : offset + size].decode("utf-8", errors="replace"))
        offset += size
    return "".join(result) if result else data.decode("utf-8", errors="replace")


def register(mcp: FastMCP, client: httpx.AsyncClient, *, read_only: bool) -> None:
    """Register Docker Swarm tools on `mcp`."""

    ro_annotations = ToolAnnotations(readOnlyHint=True)
    rw_annotations = ToolAnnotations(readOnlyHint=read_only)

    @mcp.tool(
        name="listSwarmEnvironments",
        annotations=ro_annotations,
        description=(
            "List all Portainer environments that expose a Docker Swarm API. "
            "Returns environmentId, name, accessType (agent or docker-socket), "
            "and swarmId. "
            "IMPORTANT: If the user has not specified an environmentId for a "
            "subsequent Swarm operation, call this FIRST and present the choices "
            "to the user. Do not silently pick one."
        ),
    )
    async def list_swarm_environments() -> str:
        resp = await client.get("/endpoints")
        if resp.is_error:
            raise ToolError(
                f"failed to list environments (HTTP {resp.status_code}): {resp.text[:500]}"
            )

        results: list[dict] = []

        async def _probe(ep: dict) -> None:
            try:
                r = await asyncio.wait_for(
                    client.get(f"/endpoints/{ep['Id']}/docker/swarm"),
                    timeout=3.0,
                )
                if r.is_success:
                    results.append(
                        {
                            "environmentId": ep["Id"],
                            "name": ep["Name"],
                            "accessType": _infer_access_type(ep.get("URL", "")),
                            "swarmId": r.json().get("ID", ""),
                        }
                    )
            except Exception:
                pass

        await asyncio.gather(*[_probe(ep) for ep in resp.json()])
        results.sort(key=lambda x: x["environmentId"])
        return json.dumps(results)

    @mcp.tool(
        name="listSwarmNodes",
        annotations=ro_annotations,
        description=(
            "List all nodes in a Docker Swarm cluster. "
            "Returns id, hostname, role, availability, state, addr, cpus, and memoryBytes."
        ),
    )
    async def list_swarm_nodes(
        environment_id: Annotated[int, Field(description="Portainer environment ID")],
    ) -> str:
        resp = await client.get(f"/endpoints/{environment_id}/docker/nodes")
        if resp.is_error:
            raise ToolError(
                f"failed to list swarm nodes (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        nodes = [
            {
                "id": n["ID"],
                "hostname": n["Description"]["Hostname"],
                "role": n["Spec"]["Role"].lower(),
                "availability": n["Spec"]["Availability"].lower(),
                "state": n["Status"]["State"].lower(),
                "addr": n["Status"]["Addr"],
                "cpus": n["Description"]["Resources"]["NanoCPUs"] // 1_000_000_000,
                "memoryBytes": n["Description"]["Resources"]["MemoryBytes"],
            }
            for n in resp.json()
        ]
        return json.dumps(nodes)

    @mcp.tool(
        name="listSwarmServices",
        annotations=ro_annotations,
        description=(
            "List services running in a Docker Swarm cluster. "
            "Environment variable values are intentionally excluded from the output. "
            "Use the optional stackName parameter to filter by stack."
        ),
    )
    async def list_swarm_services(
        environment_id: Annotated[int, Field(description="Portainer environment ID")],
        stack_name: Annotated[
            str | None,
            Field(description="Filter by stack name (optional)"),
        ] = None,
    ) -> str:
        resp = await client.get(
            f"/endpoints/{environment_id}/docker/services",
            params={"status": "true"},
        )
        if resp.is_error:
            raise ToolError(
                f"failed to list swarm services (HTTP {resp.status_code}): {resp.text[:500]}"
            )

        services = []
        for svc in resp.json():
            spec = svc.get("Spec", {})
            stack = (spec.get("Labels") or {}).get("com.docker.stack.namespace", "")
            if stack_name and stack != stack_name:
                continue

            mode_spec = spec.get("Mode", {})
            svc_status = svc.get("ServiceStatus") or {}
            if "Replicated" in mode_spec:
                mode = "replicated"
                desired = (mode_spec["Replicated"] or {}).get("Replicas") or 0
                running = svc_status.get("RunningTasks", 0)
            else:
                mode = "global"
                running = svc_status.get("RunningTasks", 0)
                desired = running

            ports = [
                {
                    "protocol": p.get("Protocol", "").lower(),
                    "targetPort": p.get("TargetPort", 0),
                    "publishedPort": p.get("PublishedPort", 0),
                    "publishMode": p.get("PublishMode", "").lower(),
                }
                for p in (spec.get("EndpointSpec") or {}).get("Ports", [])
            ]
            task_tmpl = spec.get("TaskTemplate", {})
            services.append(
                {
                    "id": svc["ID"],
                    "name": spec.get("Name", ""),
                    "stack": stack,
                    "image": (task_tmpl.get("ContainerSpec") or {}).get("Image", ""),
                    "mode": mode,
                    "replicas": {"desired": desired, "running": running},
                    "ports": ports,
                    "placement": (task_tmpl.get("Placement") or {}).get("Constraints", []),
                    "networks": [n["Target"] for n in spec.get("Networks", [])],
                    "createdAt": svc.get("CreatedAt", ""),
                    "updatedAt": svc.get("UpdatedAt", ""),
                }
            )
        return json.dumps(services)

    @mcp.tool(
        name="listSwarmTasks",
        annotations=ro_annotations,
        description=(
            "List tasks (container instances) in a Docker Swarm cluster. "
            "Filter by serviceName and/or desiredState (e.g. 'running', 'shutdown')."
        ),
    )
    async def list_swarm_tasks(
        environment_id: Annotated[int, Field(description="Portainer environment ID")],
        service_name: Annotated[
            str | None,
            Field(description="Filter by service name (optional)"),
        ] = None,
        desired_state: Annotated[
            str | None,
            Field(
                description="Filter by desired state, e.g. 'running' or 'shutdown' (optional)"
            ),
        ] = None,
    ) -> str:
        filters: dict[str, list[str]] = {}
        if service_name:
            filters["service"] = [service_name]
        if desired_state:
            filters["desired-state"] = [desired_state]

        params: dict = {}
        if filters:
            params["filters"] = json.dumps(filters)

        resp = await client.get(
            f"/endpoints/{environment_id}/docker/tasks", params=params
        )
        if resp.is_error:
            raise ToolError(
                f"failed to list swarm tasks (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        tasks = [
            {
                "id": t["ID"],
                "serviceId": t.get("ServiceID", ""),
                "nodeId": t.get("NodeID", ""),
                "state": (t.get("Status") or {}).get("State", ""),
                "desiredState": t.get("DesiredState", ""),
                "error": (t.get("Status") or {}).get("Err", ""),
                "updatedAt": (t.get("Status") or {}).get("Timestamp", ""),
                "containerId": (
                    (t.get("Status") or {}).get("ContainerStatus") or {}
                ).get("ContainerID", ""),
            }
            for t in resp.json()
        ]
        return json.dumps(tasks)

    @mcp.tool(
        name="getSwarmInfo",
        annotations=ro_annotations,
        description=(
            "Get a summary of a Docker Swarm cluster: "
            "manager/worker node counts, service count, and active swarm stack count."
        ),
    )
    async def get_swarm_info(
        environment_id: Annotated[int, Field(description="Portainer environment ID")],
    ) -> str:
        swarm_r, nodes_r, services_r, stacks_r = await asyncio.gather(
            client.get(f"/endpoints/{environment_id}/docker/swarm"),
            client.get(f"/endpoints/{environment_id}/docker/nodes"),
            client.get(
                f"/endpoints/{environment_id}/docker/services",
                params={"status": "true"},
            ),
            client.get("/stacks"),
        )
        for r, label in [
            (swarm_r, "swarm info"),
            (nodes_r, "nodes"),
            (services_r, "services"),
            (stacks_r, "stacks"),
        ]:
            if r.is_error:
                raise ToolError(
                    f"failed to get {label} (HTTP {r.status_code}): {r.text[:500]}"
                )

        nodes = nodes_r.json()
        manager_count = sum(
            1
            for n in nodes
            if n.get("Spec", {}).get("Role", "").lower() == "manager"
        )
        swarm_stack_count = sum(
            1
            for s in stacks_r.json()
            if s.get("EndpointId") == environment_id
            and s.get("Type") == _STACK_TYPE_SWARM
        )
        swarm = swarm_r.json()
        return json.dumps(
            {
                "id": swarm.get("ID", ""),
                "managerCount": manager_count,
                "workerCount": len(nodes) - manager_count,
                "serviceCount": len(services_r.json()),
                "stackCount": swarm_stack_count,
                "createdAt": swarm.get("CreatedAt", ""),
                "updatedAt": swarm.get("UpdatedAt", ""),
            }
        )

    @mcp.tool(
        name="getSwarmServiceLogs",
        annotations=ro_annotations,
        description=(
            "Fetch recent logs from a running Docker Swarm service. "
            "Locates the first running task for the service and retrieves its container logs. "
            "Returns an informational message if no running task is found."
        ),
    )
    async def get_swarm_service_logs(
        environment_id: Annotated[int, Field(description="Portainer environment ID")],
        service_name: Annotated[
            str, Field(description="Full service name (e.g. mystack_myservice)")
        ],
        tail: Annotated[
            int,
            Field(description="Number of log lines to return (default 100)", ge=1),
        ] = 100,
    ) -> str:
        tasks_resp = await client.get(
            f"/endpoints/{environment_id}/docker/tasks",
            params={
                "filters": json.dumps(
                    {"service": [service_name], "desired-state": ["running"]}
                )
            },
        )
        if tasks_resp.is_error:
            raise ToolError(
                f"failed to list tasks for service {service_name!r} "
                f"(HTTP {tasks_resp.status_code}): {tasks_resp.text[:500]}"
            )

        container_id = ""
        for task in tasks_resp.json():
            status = task.get("Status") or {}
            if status.get("State") == "running":
                cs = status.get("ContainerStatus") or {}
                if cs.get("ContainerID"):
                    container_id = cs["ContainerID"]
                    break

        if not container_id:
            return f"no running task found for service: {service_name}"

        logs_resp = await client.get(
            f"/endpoints/{environment_id}/docker/containers/{container_id}/logs",
            params={
                "stdout": "true",
                "stderr": "true",
                "follow": "false",
                "tail": str(tail),
            },
        )
        if logs_resp.is_error:
            raise ToolError(
                f"failed to fetch container logs (HTTP {logs_resp.status_code}): {logs_resp.text[:500]}"
            )
        return _strip_docker_frames(logs_resp.content)

    @mcp.tool(
        name="createSwarmStack",
        annotations=rw_annotations,
        description=(
            "Create a new Docker Swarm stack from a Compose file. "
            "The swarmId is resolved automatically from the target environment. "
            "Returns the new stack ID."
        ),
    )
    async def create_swarm_stack(
        environment_id: Annotated[int, Field(description="Portainer environment ID")],
        name: Annotated[str, Field(description="Stack name")],
        compose_file: Annotated[
            str, Field(description="Docker Compose file content (YAML string)")
        ],
        env: Annotated[
            list[dict] | None,
            Field(
                description='Environment variables as [{name: "KEY", value: "VAL"}] (optional)'
            ),
        ] = None,
    ) -> str:
        if read_only:
            raise ToolError("createSwarmStack is not allowed in read-only mode")

        swarm_resp = await client.get(f"/endpoints/{environment_id}/docker/swarm")
        if swarm_resp.is_error:
            raise ToolError(
                f"failed to resolve swarm ID (HTTP {swarm_resp.status_code}): {swarm_resp.text[:500]}"
            )

        body: dict = {
            "name": name,
            "stackFileContent": compose_file,
            "swarmID": swarm_resp.json().get("ID", ""),
            "fromAppTemplate": False,
        }
        if env:
            body["env"] = env

        resp = await client.post(
            "/stacks/create/swarm/string",
            params={"endpointId": environment_id},
            json=body,
        )
        if resp.is_error:
            raise ToolError(
                f"failed to create swarm stack (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        return json.dumps({"id": resp.json().get("Id"), "name": name})

    @mcp.tool(
        name="updateSwarmStack",
        annotations=rw_annotations,
        description=(
            "Update an existing Docker Swarm stack's Compose file and/or environment variables. "
            "All current environment variables must be included — omitting one removes it."
        ),
    )
    async def update_swarm_stack(
        stack_id: Annotated[int, Field(description="Portainer stack ID")],
        environment_id: Annotated[
            int,
            Field(description="Portainer environment ID where the stack runs"),
        ],
        compose_file: Annotated[
            str, Field(description="New Docker Compose file content (YAML string)")
        ],
        env: Annotated[
            list[dict] | None,
            Field(
                description='Environment variables as [{name: "KEY", value: "VAL"}] (optional)'
            ),
        ] = None,
        pull_image: Annotated[
            bool,
            Field(description="Pull latest images before deploying (default false)"),
        ] = False,
        prune: Annotated[
            bool,
            Field(
                description="Remove services not present in the new Compose file (default false)"
            ),
        ] = False,
    ) -> str:
        if read_only:
            raise ToolError("updateSwarmStack is not allowed in read-only mode")

        body: dict = {
            "stackFileContent": compose_file,
            "env": env or [],
            "prune": prune,
            "pullImage": pull_image,
        }
        resp = await client.put(
            f"/stacks/{stack_id}",
            params={"endpointId": environment_id},
            json=body,
        )
        if resp.is_error:
            raise ToolError(
                f"failed to update swarm stack (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        return json.dumps({"id": stack_id, "updated": True})

    logger.info("swarm tools registered (read_only=%s)", read_only)
