#!/usr/bin/env python3
"""Boot switching must never inspect/mount roots or change permanent settings."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('flash', TOP / 'openwrt/bundle/flash.py')
flash = importlib.util.module_from_spec(spec); spec.loader.exec_module(flash)


class Switch(unittest.TestCase):
    def run_switch(self, head, chain_error=False):
        metadata = {'persist_log_offset': 56 << 20, 'sha256_head56m': 'normal-head'}
        with contextlib.ExitStack() as stack:
            for name in ('find_adb', 'android_checks', 'steps', 'say'):
                stack.enter_context(patch.object(flash, name))
            stack.enter_context(patch.object(flash, 'boot_json', return_value=metadata))
            stack.enter_context(patch.object(flash, 'part_boot_head', return_value='partition-head'))
            read = stack.enter_context(patch.object(flash, 'su', return_value=head + '  -'))
            chain = stack.enter_context(patch.object(flash, 'bootchain'))
            if chain_error: chain.side_effect = RuntimeError('boot chain mismatch')
            # Any root probe, selector write or mount outside the misc helper
            # must fail. Storage need not be readable by Android at all.
            stack.enter_context(patch.object(flash, 'su_checked', side_effect=AssertionError('unexpected root access')))
            arm = stack.enter_context(patch.object(flash, 'arm_slot_b'))
            adb = stack.enter_context(patch.object(flash, 'adb'))
            if head not in ('normal-head', 'partition-head'):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    flash.boot_openwrt(None)
                chain.assert_not_called(); arm.assert_not_called(); adb.assert_not_called()
            elif chain_error:
                with self.assertRaisesRegex(RuntimeError, 'boot chain mismatch'): flash.boot_openwrt(None)
                arm.assert_not_called(); adb.assert_not_called()
            else:
                flash.boot_openwrt(None)
                chain.assert_called_once_with('check')
                arm.assert_called_once_with(); adb.assert_called_once_with('reboot')
            self.assertEqual(read.call_count, 1)
            self.assertIn('if=/dev/block/by-name/boot_b', read.call_args.args[0])
            self.assertNotIn('of=', read.call_args.args[0])

    def test_exact_normal_or_partition_boot_without_root_access(self):
        for head in ('normal-head', 'partition-head', 'tampered', ''):
            with self.subTest(head=head): self.run_switch(head)

    def test_boot_chain_check_failure_never_arms_or_reboots(self):
        self.run_switch('normal-head', chain_error=True)

    def test_partition_variant_hash_uses_real_installer_patch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); image = bytearray(8192); image[:8] = b'ANDROID!'
            struct.pack_into('<I', image, 40, 4)
            image[44:1580] = b'loglevel=5 e5.part_v=2'.ljust(1536, b'\0')
            (root / 'boot.img').write_bytes(image)
            with patch.object(flash, 'F', folder), patch.object(flash, 'B', str(TOP / 'openwrt/bundle')), patch.object(flash, 'SCRIPTS', folder):
                actual = flash.part_boot_head({'persist_log_offset': 4096})
            image[44:1580] = b'loglevel=5 e5.part_v=2 e5.root=part'.ljust(1536, b'\0')
            self.assertEqual(actual, hashlib.sha256(image[:4096]).hexdigest())


if __name__ == '__main__': unittest.main()
