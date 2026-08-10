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

from portainer_mcp import redaction

logger = logging.getLogger("portainer_mcp")

_STACK_TYPE_SWARM = 1


def _infer_access_type(url: str) -> str:
    if "tasks." in url:
        return "agent"
    if "docker.sock" in url:
        return "docker-socket"
    return "remote"


def _normalize_pairs(
    pairs: list[dict],
) -> tuple[list[str], dict[str, str], list[str]]:
    """Normalize a list of {name,value}/{Name,Value} pairs.

    Returns (order, values, deduped): the first-occurrence-order name list,
    a name→value map, and names that appeared more than once (collapsed to
    the last-occurring value — Portainer allows duplicate names in a
    stack's Env array, and silently dropping the later one would change
    semantics no caller asked for).
    """
    order: list[str] = []
    values: dict[str, str] = {}
    deduped: list[str] = []
    for pair in pairs:
        name = pair.get("name", pair.get("Name", ""))
        value = pair.get("value", pair.get("Value", ""))
        if value is None:
            value = ""
        if name in values:
            if name not in deduped:
                deduped.append(name)
        else:
            order.append(name)
        values[name] = str(value)
    return order, values, deduped


def _merge_env(
    current: list[dict],
    set_: dict[str, str] | None,
    unset: list[str] | None,
) -> tuple[list[dict], dict]:
    """Merge an env diff onto Portainer's current Env pairs."""
    set_ = set_ or {}
    unset_names = list(dict.fromkeys(unset or []))

    order, values, deduped = _normalize_pairs(current)
    original_names = set(order)

    added: list[str] = []
    updated: list[str] = []
    for name, value in set_.items():
        if name in values:
            if values[name] != value:
                updated.append(name)
        else:
            order.append(name)
            added.append(name)
        values[name] = value

    removed: list[str] = []
    not_found: list[str] = []
    for name in unset_names:
        if name in values:
            del values[name]
            order.remove(name)
            removed.append(name)
        else:
            not_found.append(name)

    merged = [{"name": name, "value": values[name]} for name in order]
    summary = {
        "added": added,
        "updated": updated,
        "removed": removed,
        "unchangedCount": len(original_names - set(updated) - set(removed)),
        "notFound": not_found,
        "deduped": deduped,
    }
    return merged, summary


def _replace_summary(
    current: list[dict], replacement: list[dict]
) -> tuple[list[dict], dict]:
    """Compute the merged env list and diff summary for env_replace.

    Unlike `_merge_env`, `current` is discarded entirely — the merged
    result is exactly the normalized `replacement`. The summary still
    reports added/updated/removed/unchangedCount relative to `current` so
    both the dry_run preview and the execution path can report an honest
    diff instead of a blind wipe-and-replace.
    """
    current_order, current_values, _ = _normalize_pairs(current)
    order, new_values, deduped = _normalize_pairs(replacement)
    new_names = set(order)

    added: list[str] = []
    updated: list[str] = []
    unchanged = 0
    for name in order:
        if name in current_values:
            if current_values[name] != new_values[name]:
                updated.append(name)
            else:
                unchanged += 1
        else:
            added.append(name)

    removed = [name for name in current_order if name not in new_names]

    merged = [{"name": name, "value": new_values[name]} for name in order]
    summary = {
        "added": added,
        "updated": updated,
        "removed": removed,
        "unchangedCount": unchanged,
        "notFound": [],
        "deduped": deduped,
    }
    return merged, summary


def _scrub(text: str, secret_values: set[str]) -> str:
    """Redact known secret values from an upstream error body before truncating.

    `update_swarm_stack` sends env values the caller never saw (they're
    merged server-side), so an upstream error that echoes the request
    payload could otherwise leak them — unlike other tools' error paths,
    where the payload is always the caller's own. Values are scrubbed
    longest-first so a short value can't leave part of a longer one
    unredacted, and scrubbing runs *before* truncation so a secret split
    across the 500-char boundary can't survive intact.
    """
    scrubbed = text
    for value in sorted(
        {v for v in secret_values if v and len(v) >= 4}, key=len, reverse=True
    ):
        scrubbed = scrubbed.replace(value, "[REDACTED]")
    return scrubbed[:500]


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
            "Update an existing Docker Swarm stack's Compose file and/or "
            "environment variables — env changes are a diff, not a full "
            "replacement. Variables you don't mention are preserved "
            "automatically — you don't need to call StackInspect first. "
            "StackInspect is only useful if you want to see current "
            "variable names before deciding what to change (values come "
            "back as [REDACTED], but names are visible). Use env_set to "
            "add/overwrite specific variables, env_unset to remove specific "
            "variables by name, or env_replace to discard everything and set "
            "an exact new list (env_replace=[] wipes all env vars — cannot "
            "combine env_replace with env_set/env_unset). Omit compose_file "
            "to keep the current one. Variable values are never returned — "
            "only names. Git-linked stacks are rejected by default because "
            "Portainer's update endpoint silently clears the stack's "
            "AutoUpdate setting; pass allow_git_stack=True only if losing "
            "that setting (not restored automatically) is acceptable — "
            "otherwise use StackUpdateGit / StackGitRedeploy instead. "
            "Pass dry_run=True to validate and preview only: the same reads "
            "and checks run, the merged result is computed, and the names "
            "of variables that would change are returned — without sending "
            "the update. Never returns values, in dry_run or otherwise. "
            "The preview is advisory, not a handle to apply later — the "
            "actual update re-reads the stack, so a concurrent change "
            "between the preview and a real call can make them differ."
        ),
    )
    async def update_swarm_stack(
        stack_id: Annotated[int, Field(description="Portainer stack ID")],
        environment_id: Annotated[
            int,
            Field(description="Portainer environment ID where the stack runs"),
        ],
        compose_file: Annotated[
            str | None,
            Field(
                description="New Docker Compose file content (YAML string). "
                "Omit to keep the stack's current file."
            ),
        ] = None,
        env_set: Annotated[
            dict[str, str] | None,
            Field(description="Env vars to add or overwrite, as {NAME: value}"),
        ] = None,
        env_unset: Annotated[
            list[str] | None,
            Field(description="Names of env vars to remove"),
        ] = None,
        env_replace: Annotated[
            list[dict] | None,
            Field(
                description="Discard all current env vars and replace with "
                'exactly this list, as [{"name": "KEY", "value": "VAL"}]. '
                "Use [] to wipe all env vars. Cannot combine with "
                "env_set/env_unset."
            ),
        ] = None,
        allow_git_stack: Annotated[
            bool,
            Field(
                description="Allow updating a Git-linked stack, accepting "
                "that Portainer clears its AutoUpdate setting (not restored "
                "automatically)"
            ),
        ] = False,
        dry_run: Annotated[
            bool,
            Field(
                description="Validate and preview only: perform the same "
                "reads and checks, compute the merged result, and return "
                "which variable names would change — without sending the "
                "update. Never returns values."
            ),
        ] = False,
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
        if read_only and not dry_run:
            raise ToolError(
                "updateSwarmStack is not allowed in read-only mode "
                "(dry_run=True is allowed — it only reads)"
            )

        if env_replace is not None and (env_set or env_unset):
            raise ToolError(
                "env_replace cannot be combined with env_set/env_unset — "
                "env_replace discards the current env list entirely"
            )

        stack_resp = await client.get(f"/stacks/{stack_id}")
        if stack_resp.is_error:
            raise ToolError(
                f"failed to read stack {stack_id} (HTTP {stack_resp.status_code}): "
                f"{_scrub(stack_resp.text, set())}"
            )
        stack = stack_resp.json()

        if stack.get("Type") != _STACK_TYPE_SWARM:
            raise ToolError(
                "updateSwarmStack only supports Docker Swarm stacks "
                f"(stack {stack_id} has Type={stack.get('Type')}); "
                "Kubernetes stacks don't carry Env the same way — use the "
                "Kubernetes stack tools instead"
            )

        if stack.get("GitConfig") and not allow_git_stack:
            raise ToolError(
                f"stack {stack_id} is Git-linked; PUT /stacks/{{id}} clears "
                "its AutoUpdate setting, which is not restored automatically. "
                "Use StackUpdateGit / StackGitRedeploy instead, or pass "
                "allow_git_stack=True to proceed anyway and accept losing "
                "AutoUpdate"
            )

        current_env = stack.get("Env") or []
        secret_values = {
            str(p.get("value", p.get("Value", ""))) for p in current_env
        } | set((env_set or {}).values())

        if env_replace is not None:
            merged_env, summary = _replace_summary(current_env, env_replace)
        else:
            merged_env, summary = _merge_env(current_env, env_set, env_unset)

        if not redaction.is_expose_enabled() and any(
            p.get("value") == redaction.SENTINEL for p in merged_env
        ):
            raise ToolError(
                "the merged environment variables include the redaction "
                f"sentinel {redaction.SENTINEL!r} as a value — this looks "
                "like a value read from a previous (redacted) tool response "
                "being written back verbatim, which would overwrite the "
                "actual secret with the placeholder. Pass the real value "
                "you want in env_set/env_replace, not the redacted "
                "placeholder."
            )

        def _norm(text: str) -> str:
            return text.replace("\r\n", "\n").strip()

        # compose_changed reporting is independent of compose_file resolution:
        # None means "not compared" (either compose_file was omitted — in
        # which case the current file is kept verbatim, not compared — or
        # this is a real update, where the extra GET isn't worth the latency).
        compose_changed: bool | None = None
        if compose_file is None:
            file_resp = await client.get(f"/stacks/{stack_id}/file")
            if file_resp.is_error:
                raise ToolError(
                    f"failed to read current Compose file for stack {stack_id} "
                    f"(HTTP {file_resp.status_code}): "
                    f"{_scrub(file_resp.text, secret_values)}"
                )
            compose_file = (file_resp.json() or {}).get("StackFileContent")
            if not compose_file:
                raise ToolError(
                    f"stack {stack_id} has no current Compose file content to preserve"
                )
            compose_changed = False
        elif dry_run:
            # Best-effort comparison only — this GET is informational, not
            # load-bearing, so any failure just leaves compose_changed unset
            # rather than failing the whole preview.
            try:
                cmp_resp = await client.get(f"/stacks/{stack_id}/file")
                current_compose = (
                    (cmp_resp.json() or {}).get("StackFileContent")
                    if not cmp_resp.is_error
                    else None
                )
            except (httpx.HTTPError, ValueError):
                current_compose = None
            compose_changed = (
                _norm(current_compose) != _norm(compose_file)
                if current_compose
                else None
            )

        def _build_result(*, updated: bool, env_names: list[str]) -> dict:
            result: dict = {
                "id": stack_id,
                "dry_run": dry_run,
                "updated": updated,
                "env_names": env_names,
                "env_added": summary["added"],
                "env_updated": summary["updated"],
                "env_removed": summary["removed"],
                "env_not_found": summary["notFound"],
                "env_unchanged_count": summary["unchangedCount"],
            }
            if compose_changed is not None:
                result["compose_file_changed"] = compose_changed
            if allow_git_stack and stack.get("GitConfig"):
                result["auto_update_cleared"] = True
            return result

        if dry_run:
            env_names = [p["name"] for p in merged_env]
            return json.dumps(_build_result(updated=False, env_names=env_names))

        body: dict = {
            "stackFileContent": compose_file,
            "env": merged_env,
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
                f"failed to update swarm stack (HTTP {resp.status_code}): "
                f"{_scrub(resp.text, secret_values)}"
            )

        try:
            response_json = resp.json()
        except ValueError:
            response_json = None

        response_env = response_json.get("Env") if response_json is not None else None
        if response_env is not None:
            env_names = [p.get("name", p.get("Name", "")) for p in response_env]
        else:
            env_names = [p["name"] for p in merged_env]

        return json.dumps(_build_result(updated=True, env_names=env_names))

    logger.info("swarm tools registered (read_only=%s)", read_only)
