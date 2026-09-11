"""Gun-radio control software for the four RCADS fields.

This is the cockpit, not a vehicle driver. It decides what the screen may
show and whether L3 is allowed. It does not output steering/throttle.
"""

from __future__ import annotations

from dataclasses import dataclass

from rcads_proto import (
    MODE_ASST,
    MODE_L3,
    MODE_MAN,
    MODE_TOKEN,
    STICK_DEADZONE_PCT,
    TELE_TIMEOUT_MS,
    Report,
    decode_ad_sensors,
    decode_fields,
)

PHASE_MAN = "man"
PHASE_ASST = "asst"
PHASE_L3 = "l3"
PHASE_BLOCKED = "blocked"
PHASE_TAKEOVER = "takeover"
PHASE_OVERRIDE = "override"
PHASE_LOST = "lost"

PHASE_TOKEN = {
    PHASE_MAN: "MAN",
    PHASE_ASST: "ASST",
    PHASE_L3: "L3",
    PHASE_BLOCKED: "BLK",
    PHASE_TAKEOVER: "TOVR",
    PHASE_OVERRIDE: "WHEEL",
    PHASE_LOST: "LOST",
}


def _stick_moved(steer_pct: int, thr_pct: int) -> bool:
    return abs(steer_pct) > STICK_DEADZONE_PCT or abs(thr_pct) > STICK_DEADZONE_PCT


@dataclass
class View:
    req_mode: int
    mode: int
    ready: int
    risk: int
    takeover_s: int
    phase: str
    src: str
    link_ok: bool
    alarm: bool
    beep: bool
    steer: int
    thr: int

    @property
    def token(self) -> str:
        return MODE_TOKEN[self.mode]

    @property
    def banner(self) -> str:
        if self.phase == PHASE_TAKEOVER:
            return f"TOVR {self.takeover_s}s"
        if self.phase == PHASE_OVERRIDE:
            return "WHEEL"
        if self.phase == PHASE_BLOCKED:
            return "BLOCK"
        if self.phase == PHASE_LOST:
            return "LOST"
        return "HOLD"

    @property
    def ready_text(self) -> str:
        return "READY" if self.ready else "NOT RDY"


class Cockpit:
    """One step per radio frame. Last telemetry wins until it goes stale."""

    def __init__(self) -> None:
        self._last_report: Report | None = None
        self._last_tel_ms: int | None = None
        self._src = "SA"
        self._had_telemetry = False
        self._prev_takeover = 0

    def ingest_fm(self, text: str | None, now_ms: int) -> bool:
        report = decode_fields(text)
        if report is None:
            return False
        self._accept(report, "FM", now_ms)
        return True

    def ingest_ad(
        self,
        mode: int,
        ready: int | None,
        risk: int | None,
        takeover_s: int | None,
        now_ms: int,
    ) -> None:
        self._accept(decode_ad_sensors(mode, ready, risk, takeover_s), "AD", now_ms)

    def _accept(self, report: Report, src: str, now_ms: int) -> None:
        self._last_report = report
        self._last_tel_ms = now_ms
        self._src = src
        self._had_telemetry = True

    def step(
        self,
        now_ms: int,
        req_mode: int,
        steer_pct: int,
        thr_pct: int,
        rssi_ok: bool,
    ) -> View:
        link_ok = False
        if self._last_tel_ms is not None:
            link_ok = (now_ms - self._last_tel_ms) <= TELE_TIMEOUT_MS

        if self._had_telemetry and not link_ok:
            view = View(
                req_mode=req_mode,
                mode=MODE_MAN,
                ready=0,
                risk=0,
                takeover_s=0,
                phase=PHASE_LOST,
                src="LOST",
                link_ok=False,
                alarm=True,
                beep=False,
                steer=steer_pct,
                thr=thr_pct,
            )
            self._prev_takeover = 0
            return view

        if link_ok and self._last_report is not None:
            report = self._last_report
            src = self._src
            ready = report.ready
            mode = report.mode
            risk = report.risk
            takeover_s = report.takeover_s
        else:
            report = None
            src = "SA"
            ready = 1 if rssi_ok else 0
            mode = req_mode
            risk = 0
            takeover_s = 0

        display_ready = ready if link_ok or src == "SA" else 0
        if src == "SA":
            display_ready = 1 if rssi_ok else 0

        phase = self._phase(
            req_mode=req_mode,
            mode=mode,
            ready=display_ready,
            takeover_s=takeover_s,
            steer_pct=steer_pct,
            thr_pct=thr_pct,
            linked=link_ok or src == "SA",
        )
        beep = takeover_s > 0 and self._prev_takeover == 0
        self._prev_takeover = takeover_s
        alarm = phase in (PHASE_TAKEOVER, PHASE_OVERRIDE, PHASE_LOST, PHASE_BLOCKED)
        return View(
            req_mode=req_mode,
            mode=mode,
            ready=display_ready,
            risk=risk,
            takeover_s=takeover_s,
            phase=phase,
            src=src,
            link_ok=link_ok or src == "SA",
            alarm=alarm,
            beep=beep,
            steer=steer_pct,
            thr=thr_pct,
        )

    def _phase(
        self,
        req_mode: int,
        mode: int,
        ready: int,
        takeover_s: int,
        steer_pct: int,
        thr_pct: int,
        linked: bool,
    ) -> str:
        if not linked:
            return PHASE_LOST
        if takeover_s > 0:
            return PHASE_TAKEOVER
        if mode == MODE_L3 and _stick_moved(steer_pct, thr_pct):
            return PHASE_OVERRIDE
        if req_mode == MODE_L3 and ready == 0:
            return PHASE_BLOCKED
        if mode == MODE_L3:
            return PHASE_L3
        if mode == MODE_ASST:
            return PHASE_ASST
        return PHASE_MAN
