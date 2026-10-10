"""Check media volume routing without opening hardware or playing sound."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'overlay/usr/libexec/e5-volume'


class VolumeTest(unittest.TestCase):
    def apply(self, level, sinks):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, body in {
                'pidof': 'exit 0',
                'pactl': '''if [ "$1" = list ]; then printf '%s\n' "$TEST_SINKS"; else printf 'pulse %s\n' "$*" >> "$TEST_LOG"; fi''',
                'amixer': '''printf 'mixer %s\n' "$*" >> "$TEST_LOG"''',
            }.items():
                p = root / name
                p.write_text('#!/bin/sh\n' + body + '\n')
                p.chmod(0o755)
            source = SOURCE.read_text().split('case "${1:-}" in')[0]
            script = source + '\ncard() { echo 0; }\napply "$1"\n'
            env = dict(os.environ, PATH=str(root)+':'+os.environ['PATH'], TEST_LOG=str(root/'log'), TEST_SINKS=sinks)
            subprocess.run(['sh', '-c', script, 'volume-test', str(level)], env=env, check=True)
            return (root/'log').read_text().splitlines()

    def test_speaker_and_bluetooth_share_level(self):
        lines = self.apply(5, '0\tspeaker\tmodule-alsa-sink\n1\tbluez_sink.TEST\tmodule-bluez5-device')
        self.assertIn('pulse set-sink-volume speaker 33%', lines)
        self.assertIn('pulse set-sink-volume bluez_sink.TEST 33%', lines)
        self.assertTrue(lines[-1].endswith('name=VBC DAC0 DG Set 39,39'))
        self.assertTrue(lines[0].startswith('pulse '))

    def test_mute_silences_both_pcm_and_hardware(self):
        lines = self.apply(0, '0\tspeaker\tmodule-alsa-sink')
        self.assertEqual(lines[0], 'pulse set-sink-volume speaker 0%')
        self.assertTrue(lines[-1].endswith('name=VBC DAC0 DG Set 0,0'))

    def test_direct_alsa_retains_hardware_curve(self):
        lines = self.apply(5, '')
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith('name=VBC DAC0 DG Set 19,19'))


if __name__ == '__main__':
    unittest.main()
