"""Regression checks for rejecting corrupt calibration before vendor startup."""
import array
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('nv_prepare', Path(__file__).with_name('nv-prepare.py'))
nv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nv)


class CalibrationValidation(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def image(self, body, checksum, name='nr_fixnv1_a'):
        path = Path(self.directory.name) / name
        path.write_bytes(struct.pack('<4I', 0x4e56, len(body), checksum, 101)
                         + bytes(496) + body)
        return path

    def test_valid_and_corrupt_payload(self):
        path = self.image(b'\x01\x00\x02\x00', 0xfffc)
        nv.validate_nv(path)
        contents = bytearray(path.read_bytes())
        contents[-1] ^= 1
        path.write_bytes(contents)
        with self.assertRaisesRegex(RuntimeError, 'checksum failed'):
            nv.validate_nv(path)

    def test_both_factory_accumulator_formats(self):
        body = b'\xff\xff' * 100000
        for initial in (sum(array.array('H', body)), sum(array.array('H', body)) & 0xffffffff):
            value = initial
            while value >> 16:
                value = (value & 0xffff) + (value >> 16)
            nv.validate_nv(self.image(body, value ^ 0xffff))

    def test_erased_runtime_only(self):
        path = Path(self.directory.name) / 'nr_runtimenv1'
        path.write_bytes(bytes(4096))
        nv.validate_nv(path)
        fixed = path.with_name('nr_fixnv1_a')
        fixed.write_bytes(path.read_bytes())
        with self.assertRaisesRegex(RuntimeError, 'Invalid NV header'):
            nv.validate_nv(fixed)
        path.write_bytes(bytes(4095) + b'\x01')
        with self.assertRaisesRegex(RuntimeError, 'Partially erased'):
            nv.validate_nv(path)

    def test_truncated_partition(self):
        path = self.image(b'\x01\x00', 0xfffe)
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(RuntimeError, 'Invalid NV header'):
            nv.validate_nv(path)

    def test_delta_writer_needs_identical_redundant_contents(self):
        primary = self.image(b'\x01\x00\x02\x00', 0xfffc, 'nr_fixnv1_b')
        backup = self.image(b'\x03\x00\x02\x00', 0xfffa, 'nr_fixnv2_b')
        self.assertTrue(nv.reconcile_pair(primary, backup))
        self.assertEqual(primary.read_bytes(), backup.read_bytes())
        # Vendor writes a shared checksum plus only the changed second word.
        # Without full reconciliation, backup's untouched first word stays 3.
        for path in (primary, backup):
            with path.open('r+b') as f:
                f.seek(8)
                f.write(struct.pack('<I', 0xfff8))
                f.seek(514)
                f.write(b'\x06\x00')
            nv.validate_nv(path)

    def test_recover_interrupted_backup_from_valid_primary(self):
        primary = self.image(b'\x01\x00', 0xfffe, 'nr_fixnv1_b')
        backup = self.image(b'\x02\x00', 0, 'nr_fixnv2_b')
        self.assertTrue(nv.reconcile_pair(primary, backup))
        self.assertEqual(primary.read_bytes(), backup.read_bytes())
        self.assertFalse(nv.reconcile_pair(primary, backup))

    def test_primary_failure_uses_backup(self):
        primary = self.image(b'\x01\x00', 0, 'nr_fixnv1_a')
        backup = self.image(b'\x02\x00', 0xfffd, 'nr_fixnv2_a')
        original = backup.read_bytes()
        nv.reconcile_pair(primary, backup)
        self.assertEqual(primary.read_bytes(), original)

    def test_reject_both_invalid_or_attached_without_writing(self):
        primary = self.image(b'\x01\x00', 0, 'nr_fixnv1_a')
        backup = self.image(b'\x02\x00', 0, 'nr_fixnv2_a')
        original = primary.read_bytes(), backup.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Both working'):
            nv.reconcile_pair(primary, backup)
        self.assertEqual((primary.read_bytes(), backup.read_bytes()), original)
        primary = self.image(b'\x01\x00', 0xfffe, 'nr_fixnv1_a')
        with self.assertRaisesRegex(RuntimeError, 'Detach NV loops'):
            nv.reconcile_pair(primary, backup, (primary, backup))
        self.assertEqual(backup.read_bytes(), original[1])


if __name__ == '__main__':
    unittest.main()
