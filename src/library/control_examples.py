"""Reference ``ControlConfig.controls`` examples surfaced in the admin
form so operators have pasteable templates without leaving the page.

Each entry is one archetypal device class with a short description and
the full JSON-serializable ``controls`` list. The same shapes live in
``docs/architecture/controls-architecture.md`` for prose context — these
are the machine-renderable copy of those examples.

To extend: add another dict to ``ARCHETYPES``. ``feedback_metric`` keys
should already exist in the L1 catalogue, otherwise note it in the
``setup`` field so operators know to create the metric first.
"""

from __future__ import annotations

import json
from typing import Any

ARCHETYPES: list[dict[str, Any]] = [
    {
        "slug": "smart-plug",
        "title": "Smart plug (single toggle)",
        "description": (
            "ENEROOO ER10W-style. One on/off relay with an optional "
            "third 'toggle' command. Already migrated automatically "
            "for ER10W / ER11W / ER13W."
        ),
        "setup": None,
        "controls": [
            {
                "id": "power",
                "label": "Power",
                "widget": "toggle",
                "feedback_metric": "device:relay_state",
                "states": {
                    "on":     {"wire": {"f_port": 85, "payload_hex": "01"}},
                    "off":    {"wire": {"f_port": 85, "payload_hex": "00"}},
                    "toggle": {"wire": {"f_port": 85, "payload_hex": "02"}},
                },
            }
        ],
    },
    {
        "slug": "thermostat-head",
        "title": "Thermostat head (slider + enum + button)",
        "description": (
            "Realistic LoRaWAN radiator-valve archetype: target setpoint, "
            "operating mode and an identify button. Demonstrates all "
            "three non-toggle widget primitives."
        ),
        "setup": None,
        "controls": [
            {
                "id": "target_temp",
                "label": "Target Temperature",
                "widget": "slider",
                "unit": "°C",
                "min": 5,
                "max": 30,
                "step": 0.5,
                "default": 20,
                "feedback_metric": "heat:setpoint",
                "wire": {
                    "f_port": 86,
                    "payload_template": "01{value:02X}",
                    "scale": 2,
                    "offset": 0,
                },
            },
            {
                "id": "mode",
                "label": "Mode",
                "widget": "enum",
                "feedback_metric": "device:hvac_mode",
                "options": [
                    {"value": "heat", "label": "Heating", "wire": {"f_port": 87, "payload_hex": "01"}},
                    {"value": "eco",  "label": "Eco",     "wire": {"f_port": 87, "payload_hex": "02"}},
                    {"value": "off",  "label": "Off",     "wire": {"f_port": 87, "payload_hex": "00"}},
                ],
            },
            {
                "id": "identify",
                "label": "Identify (blink LED)",
                "widget": "button",
                "wire": {"f_port": 90, "payload_hex": "FF"},
            },
        ],
    },
    {
        "slug": "gas-valve",
        "title": "Smart gas valve (toggle with confirmation)",
        "description": (
            "Destructive actuator: closing a gas line is consequential, "
            "so we set requires_confirmation. Reusable pattern for "
            "water shut-off / smart lock / breaker."
        ),
        "setup": (
            "Create the L1 metric ``device:valve_state`` first "
            "(kind=state, data_type=boolean, aggregation=last) — "
            "it's not pre-seeded."
        ),
        "controls": [
            {
                "id": "valve",
                "label": "Gas Valve",
                "widget": "toggle",
                "feedback_metric": "device:valve_state",
                "requires_confirmation": True,
                "states": {
                    "open":  {"wire": {"f_port": 85, "payload_hex": "01"}},
                    "close": {"wire": {"f_port": 85, "payload_hex": "00"}},
                },
            }
        ],
    },
]


def archetypes_for_template() -> list[dict[str, Any]]:
    """Render-ready copy of ``ARCHETYPES`` with pre-formatted JSON
    strings — saves the template from running heavy ``json.dumps``
    filters on every request."""
    return [
        {
            **arch,
            "controls_json": json.dumps(arch["controls"], indent=2, ensure_ascii=False),
        }
        for arch in ARCHETYPES
    ]
