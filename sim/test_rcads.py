from __future__ import annotations

import unittest

from rcads_ctrl import (
    PHASE_ASST,
    PHASE_BLOCKED,
    PHASE_L3,
    PHASE_LOST,
    PHASE_MAN,
    PHASE_OVERRIDE,
    PHASE_TAKEOVER,
    Cockpit,
)
from rcads_proto import (
    MODE_ASST,
    MODE_L3,
    MODE_MAN,
    Report,
    TELE_TIMEOUT_MS,
    ch_to_pct,
    decode_fields,
    encode_fields,
    load_spec,
    mode_from_sa,
    pack_crsf_flight_mode,
    unpack_crsf_flight_mode,
)


class WireProtocolTests(unittest.TestCase):
    def test_vectors(self):
        spec = load_spec()
        for row in spec["vectors"]:
            got = decode_fields(row["text"])
            self.assertIsNotNone(got, row["text"])
            self.assertEqual(got.mode, row["mode"])
            self.assertEqual(got.ready, row["ready"])
            self.assertEqual(got.risk, row["risk"])
            self.assertEqual(got.takeover_s, row["takeover_s"])

    def test_canonical_round_trip(self):
        for mode in (0, 1, 2):
            for ready in (0, 1):
                for risk in (0, 1, 50, 100):
                    for tovr in (0, 1, 30):
                        text = encode_fields(mode, ready, risk, tovr)
                        back = decode_fields(text)
                        self.assertEqual(back, Report(mode, ready, risk, tovr))
                        frame = pack_crsf_flight_mode(text)
                        self.assertEqual(unpack_crsf_flight_mode(frame), text)

    def test_reject(self):
        for text in load_spec()["reject"]:
            self.assertIsNone(decode_fields(text), text)

    def test_token_only_means_not_ready(self):
        got = decode_fields("L3")
        self.assertEqual(got, Report(MODE_L3, 0, 0, 0))

    def test_clamps_on_decode(self):
        got = decode_fields("MAN,9,200,99")
        self.assertEqual(got, Report(MODE_MAN, 1, 100, 30))

    def test_spaces_and_case(self):
        self.assertEqual(decode_fields(" asst, 1, 7, 2 "), decode_fields("ASST,1,7,2"))

    def test_does_not_parse_ardupilot_modes(self):
        for text in ("STAB", "AUTO", "LOITER", "ANGLE", "AIR"):
            self.assertIsNone(decode_fields(text), text)

    def test_bad_crc_is_drop(self):
        frame = bytearray(pack_crsf_flight_mode("L3,1,1,1"))
        frame[-1] ^= 0x01
        self.assertIsNone(unpack_crsf_flight_mode(bytes(frame)))

    def test_truncated_frame(self):
        self.assertIsNone(unpack_crsf_flight_mode(b"\xc8\x02"))

    def test_report_to_crsf(self):
        report = Report(MODE_ASST, 1, 12, 0)
        self.assertEqual(decode_fields(unpack_crsf_flight_mode(report.to_crsf())), report)

    def test_sa_mapping(self):
        self.assertEqual(mode_from_sa(-1024), MODE_MAN)
        self.assertEqual(mode_from_sa(0), MODE_ASST)
        self.assertEqual(mode_from_sa(1024), MODE_L3)

    def test_channel_percent(self):
        self.assertEqual(ch_to_pct(0), 0)
        self.assertEqual(ch_to_pct(1024), 100)
        self.assertEqual(ch_to_pct(-1024), -100)


class CockpitControlTests(unittest.TestCase):
    def setUp(self):
        self.box = Cockpit()

    def _live(self, now, req, steer=0, thr=0, rssi=True, fm=None, ad=None):
        if ad is not None:
            self.box.ingest_ad(*ad, now)
        elif fm is not None:
            self.assertTrue(self.box.ingest_fm(fm, now))
        return self.box.step(now, req, steer, thr, rssi)

    def test_no_box_follows_sa(self):
        view = self.box.step(0, MODE_ASST, 0, 0, True)
        self.assertEqual(view.phase, PHASE_ASST)
        self.assertEqual(view.src, "SA")
        self.assertEqual(view.ready, 1)
        self.assertEqual(view.risk, 0)
        self.assertEqual(view.takeover_s, 0)

    def test_no_rssi_not_ready(self):
        view = self.box.step(0, MODE_MAN, 0, 0, False)
        self.assertEqual(view.ready, 0)
        self.assertEqual(view.banner, "HOLD")

    def test_sa_l3_without_box_is_local_l3(self):
        view = self.box.step(0, MODE_L3, 0, 0, True)
        self.assertEqual(view.phase, PHASE_L3)

    def test_fm_is_vehicle_actual(self):
        view = self._live(10, MODE_L3, fm="ASST,1,12,0")
        self.assertEqual(view.mode, MODE_ASST)
        self.assertEqual(view.phase, PHASE_ASST)
        self.assertEqual(view.src, "FM")
        self.assertEqual(view.req_mode, MODE_L3)

    def test_block_when_request_l3_and_not_ready(self):
        view = self._live(10, MODE_L3, fm="MAN,0,0,0")
        self.assertEqual(view.phase, PHASE_BLOCKED)
        self.assertEqual(view.banner, "BLOCK")
        self.assertTrue(view.alarm)

    def test_takeover_owned_by_vehicle(self):
        view = self._live(10, MODE_L3, fm="L3,1,40,5")
        self.assertEqual(view.phase, PHASE_TAKEOVER)
        self.assertEqual(view.takeover_s, 5)
        later = self.box.step(20, MODE_L3, 0, 0, True)
        self.assertEqual(later.takeover_s, 5)

    def test_takeover_beep_on_rising_edge(self):
        a = self._live(10, MODE_L3, fm="L3,1,10,0")
        self.assertFalse(a.beep)
        b = self._live(20, MODE_L3, fm="L3,1,10,4")
        self.assertTrue(b.beep)
        c = self._live(30, MODE_L3, fm="L3,1,10,3")
        self.assertFalse(c.beep)

    def test_wheel_override_in_l3(self):
        view = self._live(10, MODE_L3, steer=40, fm="L3,1,5,0")
        self.assertEqual(view.phase, PHASE_OVERRIDE)
        self.assertEqual(view.banner, "WHEEL")

    def test_deadzone_does_not_override(self):
        view = self._live(10, MODE_L3, steer=10, thr=-8, fm="L3,1,5,0")
        self.assertEqual(view.phase, PHASE_L3)

    def test_takeover_beats_override(self):
        view = self._live(10, MODE_L3, steer=80, fm="L3,1,5,2")
        self.assertEqual(view.phase, PHASE_TAKEOVER)

    def test_ad_sensors_win_over_fm(self):
        self.box.ingest_fm("MAN,1,0,0", 10)
        view = self._live(11, MODE_MAN, ad=(MODE_L3, 1, 9, 0))
        self.assertEqual(view.src, "AD")
        self.assertEqual(view.mode, MODE_L3)

    def test_invalid_fm_ignored(self):
        self.assertFalse(self.box.ingest_fm("AUTO", 10))
        view = self.box.step(10, MODE_MAN, 0, 0, True)
        self.assertEqual(view.src, "SA")

    def test_timeout_drops_to_lost(self):
        self._live(0, MODE_L3, fm="L3,1,1,0")
        view = self.box.step(TELE_TIMEOUT_MS + 1, MODE_L3, 0, 0, True)
        self.assertEqual(view.phase, PHASE_LOST)
        self.assertEqual(view.mode, MODE_MAN)
        self.assertEqual(view.ready, 0)
        self.assertEqual(view.risk, 0)
        self.assertEqual(view.takeover_s, 0)
        self.assertEqual(view.banner, "LOST")

    def test_fresh_packet_clears_lost(self):
        self._live(0, MODE_L3, fm="L3,1,1,0")
        self.box.step(TELE_TIMEOUT_MS + 1, MODE_L3, 0, 0, True)
        view = self._live(TELE_TIMEOUT_MS + 20, MODE_L3, fm="ASST,1,0,0")
        self.assertEqual(view.phase, PHASE_ASST)
        self.assertEqual(view.src, "FM")

    def test_within_timeout_keeps_l3(self):
        self._live(0, MODE_L3, fm="L3,1,3,0")
        view = self.box.step(TELE_TIMEOUT_MS, MODE_L3, 0, 0, True)
        self.assertEqual(view.phase, PHASE_L3)

    def test_radio_does_not_invent_risk(self):
        view = self.box.step(0, MODE_ASST, 0, 0, True)
        self.assertEqual(view.risk, 0)


if __name__ == "__main__":
    unittest.main()
