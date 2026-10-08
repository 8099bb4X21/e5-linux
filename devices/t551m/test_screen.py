"""Hardware-independent power sequencing regression tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('power', Path(__file__).with_name('infoscreen') / 'screen-power.py')
power = importlib.util.module_from_spec(spec)
spec.loader.exec_module(power)


class ScreenPowerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bl = self.root / 'class/backlight/panel/brightness'
        self.touch = self.root / 'class/input/input7/inhibited'
        for p in [self.bl, self.touch]:
            p.parent.mkdir(parents=True)
            p.write_text('0\n')
        (self.touch.parent / 'name').write_text('tlsc6x_touch\n')
        self.sys = patch.object(power, 'SYS', self.root)
        self.lock = patch.object(power, 'LOCK', self.root / 'power.lock')
        self.sys.start(); self.lock.start()

    def tearDown(self):
        self.sys.stop(); self.lock.stop(); self.tmp.cleanup()

    def test_dark_inhibits_and_wake_restores(self):
        for _ in range(5):
            power.reconcile(0, True)
            self.assertEqual(self.touch.read_text().strip(), '1')
            power.reconcile(180, True)
            self.assertEqual(self.touch.read_text().strip(), '0')
            self.assertEqual(self.bl.read_text().strip(), '180')

    def test_explicit_touch_off_survives_wake(self):
        power.reconcile(0, False)
        power.reconcile(255, False)
        self.assertEqual(self.touch.read_text().strip(), '1')
        power.reconcile(allowed=True)
        self.assertEqual(self.touch.read_text().strip(), '0')

    def test_external_backlight_and_service_restart_reconcile(self):
        self.bl.write_text('0\n'); self.touch.write_text('0\n')
        power.reconcile(allowed=True)
        self.assertEqual(self.touch.read_text().strip(), '1')
        self.bl.write_text('120\n')
        power.reconcile(allowed=True)
        self.assertEqual(self.touch.read_text().strip(), '0')

    def test_inhibit_precedes_backlight_write(self):
        events=[]
        original=Path.write_text
        def track(path, text, *args, **kwargs):
            events.append((path.name,text.strip()))
            return original(path,text,*args,**kwargs)
        with patch.object(Path, 'write_text', track):
            power.reconcile(0, True)
            power.reconcile(255, True)
        self.assertEqual(events,[('inhibited','1'),('brightness','0'),('inhibited','0'),('brightness','255')])


if __name__ == '__main__':
    unittest.main()
