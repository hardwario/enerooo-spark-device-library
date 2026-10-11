"""Which sidebar nav section each page belongs to.

One explicit table instead of substring checks on URL names in the template:
those missed pages whose name didn't contain the section word (e.g. the
model config forms), so no nav item was highlighted on them. A test checks
that every named URL appears here, so new pages can't silently drift.
"""

_MODELS = [
    "model-list",
    "model-create",
    "model-detail",
    "model-edit",
    "model-delete",
    "model-history-snapshot",
    "model-history-diff",
    "modbus-config-edit",
    "control-config-edit",
    "wmbus-config-edit",
    "lorawan-config-edit",
    "processor-config-edit",
    "alarm-config-edit",
    "provisioning-edit",
    "model-assets",
    "document-add",
    "document-delete",
    "document-file",
    "image-upload",
    "image-delete",
    "image-file",
    "procedure-edit",
    "procedure-delete",
    "register-list",
    "register-create",
    "register-edit",
    "register-delete",
]

_SECTIONS = {
    "dashboard": ["library:dashboard"],
    "metrics": [
        "library:metric-list",
        "library:metric-create",
        "library:metric-detail",
        "library:metric-edit",
        "library:metric-delete",
        "library:metric-history-snapshot",
        "library:metric-history-diff",
    ],
    "alarms": ["library:alarm-list", "library:alarm-create", "library:alarm-edit", "library:alarm-delete"],
    "device-types": [
        "library:devicetype-list",
        "library:devicetype-create",
        "library:devicetype-detail",
        "library:devicetype-edit",
        "library:devicetype-delete",
        "library:devicetype-history-snapshot",
        "library:devicetype-history-diff",
    ],
    "vendors": ["library:vendor-list", "library:vendor-create", "library:vendor-detail", "library:vendor-delete"],
    "models": [f"library:{name}" for name in _MODELS],
    "wmbus-mappings": ["library:wmbus-mappings"],
    "versions": [
        "library:version-list",
        "library:version-compare",
        "library:version-create",
        "library:version-detail",
        "library:version-export",
    ],
    "api-keys": [
        "library:apikey-list",
        "library:apikey-create",
        "library:apikey-detail",
        "library:apikey-revoke",
        "library:apikey-enable",
        "library:apikey-toggle-write",
        "library:apikey-regenerate",
        "library:apikey-delete",
    ],
    "gateways": ["library:gateway-list", "library:gateway-create", "library:gateway-edit", "library:gateway-delete"],
    "export": ["library:import", "library:export", "library:export-download"],
    "users": ["core:user-list", "core:user-role"],
    "invitations": [
        "core:invitation-list",
        "core:invitation-create",
        "core:invitation-revoke",
        "core:invitation-resend",
    ],
    "activity": ["auditlog:log-list"],
    # Reached from the user menu, not the sidebar.
    "account": ["core:profile", "core:accept-invitation"],
}

NAV_SECTIONS = {view_name: section for section, names in _SECTIONS.items() for view_name in names}


def nav_section_for(view_name: str | None) -> str | None:
    """Section for a resolved ``namespace:url_name``, or None outside the app pages."""
    return NAV_SECTIONS.get(view_name or "")
