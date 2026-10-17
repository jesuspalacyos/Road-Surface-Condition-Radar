"""Synthetic software checks only; not an ice-detection accuracy test."""
import struct
import unittest
import numpy as np
from ice_radar import Decoder, MAGIC, ROOT, config, fit, predict


def packet(values, frame=1, extra=False):
    payload = np.asarray(values, dtype='<u2').tobytes()
    tlvs = struct.pack('<II', 2, len(payload))+payload
    if extra:
        tlvs += struct.pack('<II', 6, 24)+bytes(24)
    size = 40+len(tlvs)
    pad = (-size) % 32
    return MAGIC+struct.pack('<8I', 0x03060000, size+pad, 0xA6843, frame, 0, 0, 2 if extra else 1, 0)+tlvs+bytes(pad)


class CoreTests(unittest.TestCase):
    def test_config(self):
        _, n, spacing, _ = config(ROOT/'road_profile.cfg')
        self.assertEqual(n, 256)
        self.assertAlmostEqual(spacing, .243949, places=5)

    def test_fragmentation_and_multiple_tlvs(self):
        values = np.arange(256)
        wire = b'noise'+packet(values, 41, True)+packet(values+1, 42)
        d, frames = Decoder(256), []
        for start in range(0, len(wire), 7):
            frames.extend(d.feed(wire[start:start+7]))
        self.assertEqual([f for f, _ in frames], [41, 42])
        np.testing.assert_equal(frames[0][1], values)
        np.testing.assert_equal(frames[1][1], values+1)

    def test_bad_tlv_then_recovery(self):
        bad = bytearray(packet(np.arange(256)))
        struct.pack_into('<I', bad, 44, 999999)
        d = Decoder(256)
        frames = d.feed(bad+packet(np.arange(256), 2))
        self.assertEqual([f for f, _ in frames], [2])
        self.assertEqual(d.bad, 1)

    def test_bad_packet_size_then_recovery(self):
        bad = bytearray(packet(np.arange(256)))
        struct.pack_into('<I', bad, 12, 999999)
        d = Decoder(256)
        frames = d.feed(bad+packet(np.arange(256), 2))
        self.assertEqual([f for f, _ in frames], [2])

    def test_wrong_profile_length(self):
        self.assertEqual(Decoder(256).feed(packet(np.arange(128))), [])

    def test_sample_matching_and_rejection(self):
        rng = np.random.default_rng(2)
        sessions = []
        for label, value in [('dry',1000), ('wet',2000), ('ice',3000)]:
            for _ in range(3):
                sessions.append({'label':label, 'windows':rng.normal(value, 5, (12,4)).tolist()})
        model = fit(sessions)
        self.assertEqual(predict(model, np.full(4,3000))[0], 'ice')
        self.assertEqual(predict(model, np.full(4,2000))[0], 'wet')
        self.assertEqual(predict(model, np.full(4,1000))[0], 'dry')
        self.assertEqual(predict(model, np.full(4,2500))[0], 'unknown')
        self.assertEqual(predict(model, np.full(4,10000))[0], 'unknown')

    def test_identical_classes_reject(self):
        sessions = [{'label':k, 'windows':np.ones((12,4)).tolist()}
                    for k in ('dry','wet','ice') for _ in range(3)]
        self.assertEqual(predict(fit(sessions), np.ones(4))[0], 'unknown')


if __name__ == '__main__':
    unittest.main()
