"""Compatibility shim. Protocol lives in rcads_proto, control in rcads_ctrl."""

from rcads_ctrl import Cockpit
from rcads_proto import (
    decode_fields,
    encode_fields,
    load_spec,
    pack_crsf_flight_mode,
    unpack_crsf_flight_mode,
)


def cockpit_flags(state, steer_pct: int, thr_pct: int) -> dict:
    box = Cockpit()
    report = state if hasattr(state, "to_fm") else None
    fm = report.to_fm() if report else encode_fields(state["mode"], state["ready"], state["risk"], state["takeover_s"])
    box.ingest_fm(fm, 0)
    view = box.step(0, state["mode"] if isinstance(state, dict) else report.mode, steer_pct, thr_pct, True)
    return {
        "token": view.token,
        "ready_text": view.ready_text,
        "banner": view.banner,
        "alarm": view.alarm,
        "override": view.phase == "override",
    }
