"""RCADS v1 wire protocol: four fields on CRSF flight-mode (0x21).

Vehicle sends. Radio never invents risk or takeover, and never decrements
takeover_s. Missing/invalid text is a parse failure, not a default L3.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path

CRSF_SYNC = 0xC8
CRSF_TYPE_FLIGHT_MODE = 0x21
CRSF_MAX_PAYLOAD = 60

MODE_MAN = 0
MODE_ASST = 1
MODE_L3 = 2
MODE_TOKEN = {MODE_MAN: "MAN", MODE_ASST: "ASST", MODE_L3: "L3"}
TOKEN_MODE = {name: i for i, name in MODE_TOKEN.items()}

READY_MIN, READY_MAX = 0, 1
RISK_MIN, RISK_MAX = 0, 100
TAKEOVER_MIN, TAKEOVER_MAX = 0, 30

# Radio-side control constants (not on the wire).
TELE_TIMEOUT_MS = 1500
STICK_DEADZONE_PCT = 18
SA_DOWN, SA_MID, SA_UP = -1024, 0, 1024

FM_RE = re.compile(
    r"^(MAN|ASST|L3)(?:,(\d{1,3}),(\d{1,3}),(\d{1,2}))?$",
    re.IGNORECASE,
)


def clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def mode_from_sa(sa_value: int) -> int:
    """MT12 SA 3-pos: down=MAN, mid=ASST, up=L3."""
    if sa_value > 512:
        return MODE_L3
    if sa_value < -512:
        return MODE_MAN
    return MODE_ASST


def ch_to_pct(ch: int) -> int:
    return int(ch / 10.24)


@dataclass(frozen=True)
class Report:
    """The four fields. Vehicle is source of truth."""

    mode: int
    ready: int
    risk: int
    takeover_s: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", clamp(int(self.mode), MODE_MAN, MODE_L3))
        object.__setattr__(self, "ready", clamp(int(self.ready), READY_MIN, READY_MAX))
        object.__setattr__(self, "risk", clamp(int(self.risk), RISK_MIN, RISK_MAX))
        object.__setattr__(self, "takeover_s", clamp(int(self.takeover_s), TAKEOVER_MIN, TAKEOVER_MAX))

    @property
    def token(self) -> str:
        return MODE_TOKEN[self.mode]

    def to_fm(self) -> str:
        return f"{self.token},{self.ready},{self.risk},{self.takeover_s}"

    def to_crsf(self) -> bytes:
        return pack_crsf_flight_mode(self.to_fm())


def encode_fields(mode: int, ready: int, risk: int, takeover_s: int) -> str:
    return Report(mode, ready, risk, takeover_s).to_fm()


def decode_fields(text: str | None) -> Report | None:
    if not text:
        return None
    raw = text.strip().strip("\x00").replace(" ", "")
    match = FM_RE.match(raw)
    if not match:
        return None
    mode = TOKEN_MODE[match.group(1).upper()]
    if match.group(2) is None:
        return Report(mode, 0, 0, 0)
    return Report(mode, int(match.group(2)), int(match.group(3)), int(match.group(4)))


def decode_ad_sensors(mode, ready=None, risk=None, takeover_s=None) -> Report:
    """Named EdgeTX sensors ADmd/ADrd/ADrk/ADto."""
    return Report(
        mode,
        0 if ready is None else ready,
        0 if risk is None else risk,
        0 if takeover_s is None else takeover_s,
    )


def crc8_dvb_s2(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def pack_crsf_flight_mode(text: str) -> bytes:
    payload = text.encode("ascii") + b"\x00"
    if len(payload) > CRSF_MAX_PAYLOAD:
        raise ValueError("flight-mode text too long for CRSF")
    body = bytes([CRSF_TYPE_FLIGHT_MODE]) + payload
    return bytes([CRSF_SYNC, len(body) + 1]) + body + bytes([crc8_dvb_s2(body)])


def unpack_crsf_flight_mode(frame: bytes) -> str | None:
    if len(frame) < 5 or frame[0] != CRSF_SYNC:
        return None
    length = frame[1]
    body = frame[2 : 2 + length]
    if len(body) != length or body[0] != CRSF_TYPE_FLIGHT_MODE:
        return None
    if crc8_dvb_s2(body[:-1]) != body[-1]:
        return None
    try:
        return body[1:-1].split(b"\x00", 1)[0].decode("ascii")
    except UnicodeDecodeError:
        return None


def load_spec() -> dict:
    path = Path(__file__).resolve().parents[1] / "protocol" / "rcads.json"
    return json.loads(path.read_text(encoding="utf-8"))
