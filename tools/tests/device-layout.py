#!/usr/bin/env python3
"""Check overlay precedence, permissions, profile boundaries and safe output replacement."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('device_layout', TOP / 'tools/device-layout.py')
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


class DeviceLayout(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.top = Path(self.temp.name)
        device = self.top / 'device'
        device.mkdir()
        names = ['linux_device_common', 'openwrt_device_common', 'openwrt_device_e5']
        (device / 'manifest.json').write_text(json.dumps({'profiles': {'openwrt': {'e5': names}}}))
        for name in names:
            repo = device / name
            (repo / 'overlay/etc').mkdir(parents=True)
            system, _, model = name.partition('_device_')
            (repo / 'profile.json').write_text(json.dumps({'schema': 1, 'system': system, 'model': model}))
            (repo / 'overlay/etc/order').write_text(name)
        self.top_patch = patch.object(layout, 'TOP', self.top)
        self.layout_patch = patch.object(layout, 'LAYOUT', device / 'manifest.json')
        self.top_patch.start(); self.layout_patch.start()
        self.addCleanup(self.top_patch.stop); self.addCleanup(self.layout_patch.stop)

    def test_device_overlay_wins_and_binary_mode_survives(self):
        src = self.top / 'device/linux_device_common/overlay/etc/binary'
        src.write_bytes(b'\x00\r\n\xff'); src.chmod(0o755)
        out = self.top / 'work/overlay'
        layout.compose('openwrt', 'e5', out)
        self.assertEqual((out / 'etc/order').read_text(), 'openwrt_device_e5')
        self.assertEqual((out / 'etc/binary').read_bytes(), src.read_bytes())
        self.assertEqual((out / 'etc/binary').stat().st_mode & 0o777, 0o755)
        layout.compose('openwrt', 'e5', out)

    def test_private_files_are_explicit_and_sources_stay_intact(self):
        private = self.top / 'work/private'
        (private / 'etc').mkdir(parents=True)
        (private / 'etc/private').write_text('unit-specific')
        out = self.top / 'work/overlay'
        layout.compose('openwrt', 'e5', out)
        self.assertFalse((out / 'etc/private').exists())
        layout.compose('openwrt', 'e5', out, private)
        self.assertEqual((out / 'etc/private').read_text(), 'unit-specific')
        self.assertTrue((private / 'etc/private').exists())

    def test_unknown_board_and_uninitialized_repository_fail(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            layout.repositories('openwrt', 'unknown')
        (self.top / 'device/openwrt_device_e5/profile.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing device repository'):
            layout.repositories('openwrt', 'e5')

    def test_existing_data_and_source_directories_cannot_be_replaced(self):
        out = self.top / 'existing'
        out.mkdir(); (out / 'keep').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'Refusing'):
            layout.compose('openwrt', 'e5', out)
        with self.assertRaisesRegex(ValueError, 'separate'):
            layout.compose('openwrt', 'e5', self.top / 'device/openwrt_device_e5')
        self.assertEqual((out / 'keep').read_text(), 'keep')

    def test_repository_cannot_impersonate_another_board(self):
        (self.top / 'device/openwrt_device_e5/profile.json').write_text(json.dumps({
            'schema': 1, 'system': 'openwrt', 'model': 'm8'}))
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            layout.repositories('openwrt', 'e5')


if __name__ == '__main__':
    unittest.main()
