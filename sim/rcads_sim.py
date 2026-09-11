"""Drive the cockpit FSM from the keyboard."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rcads_ctrl import Cockpit
from rcads_proto import MODE_ASST, MODE_L3, MODE_MAN, encode_fields


def _getch():
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            return ""
        return ch
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def render(view, fm: str) -> str:
    req = ["MAN", "ASST", "L3"][view.req_mode]
    return "\n".join(
        [
            "+" + "-" * 34 + "+",
            f"| RCADS {view.token:>5}  req={req:<4} {view.phase:>8} |",
            f"| {view.ready_text:<8} {view.src:<4}  {fm:<16} |",
            f"| ST {view.steer:>4}   TH {view.thr:>4}               |",
            f"| RISK {view.risk:<3} {view.banner:>22} |",
            "| 123 req  r ready  [] risk  t tovr |",
            "| as wheel  wz trig  f feed  q quit |",
            "+" + "-" * 34 + "+",
        ]
    )


def main() -> None:
    box = Cockpit()
    req, veh, ready, risk, tovr = MODE_ASST, MODE_ASST, 1, 0, 0
    steer, thr = 0, 0
    now = 0
    feed = True
    if not sys.stdin.isatty() or "--once" in sys.argv:
        box.ingest_fm("L3,1,23,5", 0)
        print(render(box.step(0, MODE_L3, 40, -10, True), "L3,1,23,5"))
        return
    while True:
        now += 50
        fm = encode_fields(veh, ready, risk, tovr)
        if feed:
            box.ingest_fm(fm, now)
        view = box.step(now, req, steer, thr, True)
        os.system("cls" if os.name == "nt" else "clear")
        print(render(view, fm if feed else "(no fm)"))
        key = _getch()
        if key in ("q", "Q", "\x03"):
            break
        if key == "1":
            req = MODE_MAN
            veh = MODE_MAN
        elif key == "2":
            req = MODE_ASST
            veh = MODE_ASST
        elif key == "3":
            req = MODE_L3
            veh = MODE_L3
        elif key in ("r", "R"):
            ready = 0 if ready else 1
        elif key == "[":
            risk = max(0, risk - 5)
        elif key == "]":
            risk = min(100, risk + 5)
        elif key in ("t", "T"):
            tovr = 0 if tovr else 5
        elif key == "a":
            steer = max(-100, steer - 10)
        elif key == "s":
            steer = min(100, steer + 10)
        elif key == "w":
            thr = min(100, thr + 10)
        elif key == "z":
            thr = max(-100, thr - 10)
        elif key in ("f", "F"):
            feed = not feed


if __name__ == "__main__":
    main()
