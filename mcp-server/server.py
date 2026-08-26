"""Device Library MCP Server.

Wraps the library's /api/v1/agent/ endpoints as MCP tools so an AI agent can
analyze the library and prepare device-definition edits. Every write lands as
a DRAFT under the ``mcp-agent`` history identity — Spark instances only ever
receive what a human reviews and publishes as a LibraryVersion, so publishing
is deliberately not exposed here.

Transport:
- Default (no env var): stdio — for Claude Code launching the process directly
- MCP_TRANSPORT=http: streamable-http on MCP_HOST:MCP_PORT — for Docker
"""

import json
import os

from fastmcp import FastMCP

from config import DEFAULT_INSTANCE, client_for, describe_instances

_instance_list = ", ".join(
    f"'{i['name']}' ({i['description']})" for i in describe_instances()["instances"]
)

mcp = FastMCP(
    "device-library",
    instructions=(
        "Enerooo Device Library — read and draft-edit device definitions "
        "(vendor models, alarm mappings).\n\n"
        f"Configured instances (default='{DEFAULT_INSTANCE}'): {_instance_list}\n\n"
        "Key facts:\n"
        "- Every edit is a DRAFT: Spark instances only see the snapshot pinned "
        "by the last published LibraryVersion. Publishing is human-only, in the "
        "library UI, after reviewing the unpublished diff.\n"
        "- `library_status` shows the current version and every unpublished "
        "draft — check it before and after making edits.\n"
        "- Whether writes are allowed is a server-side setting "
        "(AGENT_API_ALLOW_WRITES) per deployment; a disabled write returns 403.\n"
        "- Model identity is the `key` UUID (stable across renames). Find it "
        "with `list_models`.\n\n"
        "Writes cover everything the UI edits: model fields, all config "
        "sections (processor/alarm/modbus/wmbus/lorawan/control), Modbus "
        "registers, and the catalogues (vendors, metrics, device_types, "
        "alarms). Every write is validated by the same Django form the UI "
        "uses and lands in history as 'mcp-agent'. Writes use merge "
        "semantics: send only the fields you change — except JSON-list "
        "fields (mappings, field_mappings, controls, metrics profile), "
        "which are replaced whole.\n\n"
        "Typical alarm-mapping workflow: Spark reports an unmapped alarm flag → "
        "`list_models(q=<driver>)` → `get_model(key)` to see the current "
        "alarm_config → `set_model_config(key, 'alarm', ...)` with the full "
        "replacement mappings list → tell the operator to review and publish."
    ),
)


def _get(instance: str, path: str, params: dict | None = None) -> str:
    with client_for(instance) as client:
        resp = client.get(f"/{path.lstrip('/')}", params=params)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def list_instances() -> str:
    """List configured library instances (local dev / production)."""
    return json.dumps(describe_instances(), indent=2, ensure_ascii=False)


@mcp.tool()
def library_status(instance: str = "") -> str:
    """Current published version + every unpublished draft entity.

    The unpublished list is exactly what the operator will see in the publish
    review, so use it to verify what your edits changed — and to check whether
    unrelated drafts are already pending before you add more.
    """
    return _get(instance, "status/")


@mcp.tool()
def list_models(
    q: str = "",
    technology: str = "",
    device_type: str = "",
    missing_alarm_config: bool = False,
    instance: str = "",
) -> str:
    """Search vendor models. Returns key (UUID), vendor, name, technology.

    Args:
        q: Substring match on name, model number, vendor, or wmbusmeters driver
           (e.g. 'caltose' finds every model decoded by that driver).
        technology: modbus | wmbus | lorawan | chester
        device_type: L2 slug, e.g. heat_cost_allocator, water_meter
        missing_alarm_config: only models with NO alarm mapping yet — the
            worklist for unmapped-alarm-flag reports from Spark.
    """
    params: dict = {}
    if q:
        params["q"] = q
    if technology:
        params["technology"] = technology
    if device_type:
        params["device_type"] = device_type
    if missing_alarm_config:
        params["missing_alarm_config"] = "1"
    return _get(instance, "models/", params)


@mcp.tool()
def get_model(key: str, instance: str = "") -> str:
    """Full definition snapshot of one vendor model by key UUID.

    Includes every config the library holds for it (processor/field mappings,
    alarm mappings, modbus/wmbus/lorawan config, control config) — the same
    snapshot a published LibraryVersion would ship to Spark.
    """
    return _get(instance, f"models/{key}/")


@mcp.tool()
def model_history(key: str, instance: str = "") -> str:
    """Change history of a model: version, action, author, per-field diff.

    Agent edits appear under user 'mcp-agent', human UI edits under their
    username — use this to see what changed and who changed it.
    """
    return _get(instance, f"models/{key}/history/")


@mcp.tool()
def set_model_config(key: str, section: str, data: dict, instance: str = "") -> str:
    """Edit one config section of a model. Draft only, merge semantics.

    Args:
        key: Model key UUID.
        section: processor | alarm | modbus | wmbus | lorawan | control
        data: Fields to change; omitted fields keep their current value.
            JSON-list fields are replaced whole — fetch current values via
            get_model first and send the complete new list:
            - alarm:     {match_type, mappings:[{match, severity, alarm?,
                          description?, source?}]}  severity: info|warning|critical
            - processor: {field_mappings:[...], extra_mappings:[...]}
            - wmbus:     {manufacturer_code, wmbus_version, wmbus_device_type,
                          encryption_required, shared_encryption_key,
                          wmbusmeters_driver, is_mvt_default}
            - lorawan:   {device_class, lorawan_version, lorawan_phy_version,
                          frequency_plan_id, join_eui_default, supports_join,
                          downlink_f_port, codec_format, payload_codec}
            - modbus:    {function, byte_order, word_order} (registers have
                          their own upsert_register tool)
            - control:   {controllable, controls:[...]}

    Validated server-side by the UI's own form; recorded in history as
    'mcp-agent'. Spark instances receive it only after a human publishes —
    remind the operator to review the diff (library_status) and publish.
    """
    with client_for(instance) as client:
        resp = client.put(f"/models/{key}/config/{section}/", json=data)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def update_model(key: str, fields: dict, instance: str = "") -> str:
    """Edit a model's own fields. Draft only, merge semantics.

    fields may contain: name, model_number, description, technology
    (modbus|wmbus|lorawan|chester), vendor (vendor id from
    list_catalog('vendors')), device_type_fk (device type id from
    list_catalog('device_types')).
    """
    with client_for(instance) as client:
        resp = client.put(f"/models/{key}/", json=fields)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def create_model(fields: dict, instance: str = "") -> str:
    """Create a vendor model. Draft only.

    Required: vendor (id from list_catalog('vendors')), name, model_number,
    technology. Recommended: device_type_fk (id from
    list_catalog('device_types')), description. Configure sections afterwards
    with set_model_config using the returned key.
    """
    with client_for(instance) as client:
        resp = client.post("/models/", json=fields)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def delete_model(key: str, instance: str = "") -> str:
    """Delete a vendor model (history keeps a DELETED snapshot). Confirm with
    the operator before deleting anything a Spark instance may reference."""
    with client_for(instance) as client:
        resp = client.delete(f"/models/{key}/")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def list_catalog(kind: str, q: str = "", instance: str = "") -> str:
    """List a catalogue: vendors | metrics | device_types | alarms.

    Returns ids used by the write tools (vendor/device_type_fk on models,
    pk for upsert_catalog). metrics = L1 canonical metric keys with units and
    validation ranges; device_types = L2 profiles with their metrics list;
    alarms = the L1 alarm identities alarm mappings can reference.
    """
    params = {"q": q} if q else None
    return _get(instance, f"catalog/{kind}/", params)


@mcp.tool()
def upsert_catalog(kind: str, data: dict, pk: str = "", instance: str = "") -> str:
    """Create (no pk) or edit (pk) a catalogue entry. Draft only, merge
    semantics on edit.

    kinds and their fields:
        vendors:      {name, slug}
        metrics:      {key ('ns:name'), label, unit, data_type, kind,
                       description, min_value, max_value, monotonic, aggregation}
        device_types: {code, label, description, icon, metrics:[...profile]}
                      — a code rename auto-propagates to every model using it
        alarms:       {key, label, default_severity, description}

    Metric and device-type changes are versioned in their own history tables,
    attributed to 'mcp-agent'.
    """
    with client_for(instance) as client:
        if pk:
            resp = client.put(f"/catalog/{kind}/{pk}/", json=data)
        else:
            resp = client.post(f"/catalog/{kind}/", json=data)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def delete_catalog(kind: str, pk: str, instance: str = "") -> str:
    """Delete a catalogue entry. Deleting a metric or device type other
    models reference is destructive — confirm with the operator first."""
    with client_for(instance) as client:
        resp = client.delete(f"/catalog/{kind}/{pk}/")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def upsert_register(key: str, data: dict, register_id: str = "", instance: str = "") -> str:
    """Create (no register_id) or edit a Modbus register on a model. The
    model must already have a modbus config (set_model_config(key, 'modbus')).

    data: {field_name, field_unit, address, data_type
           (int16|uint16|int32|uint32|int64|uint64|float32), scale, offset}.
    Registers are listed in get_model's `registers` field.
    """
    with client_for(instance) as client:
        if register_id:
            resp = client.put(f"/models/{key}/registers/{register_id}/", json=data)
        else:
            resp = client.post(f"/models/{key}/registers/", json=data)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@mcp.tool()
def delete_register(key: str, register_id: str, instance: str = "") -> str:
    """Delete a Modbus register from a model."""
    with client_for(instance) as client:
        resp = client.delete(f"/models/{key}/registers/{register_id}/")
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.run(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "9000")),
        )
    else:
        mcp.run()
