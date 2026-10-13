#!/usr/bin/env python3
"""Run packaged launchers and menu choices without ADB or disk operations."""
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
api = runpy.run_path(str(TOP / 'openwrt/bundle/install-entrypoints.py'))
spec = importlib.util.spec_from_file_location('flasher', TOP / 'openwrt/bundle/flash.py')
flash = importlib.util.module_from_spec(spec); spec.loader.exec_module(flash)


class Entrypoints(unittest.TestCase):
    def source(self, path):
        path.mkdir()
        for name in ('flash.py', 'flash.cmd', 'flash.sh', 'part-two-stage.py'):
            shutil.copy2(TOP / 'openwrt/bundle' / name, path / name)

    def test_menu_selects_exact_action_and_cancel_does_not_install(self):
        for choice, field in [('1','tf'),('2','part'),('3','reinstall_part'),('4','resume_part'),
                              ('5','boot_openwrt'),('6','update'),('0',None)]:
            a=SimpleNamespace(tf=False,part=False,reinstall_part=False,resume_part=None,
                              boot_openwrt=False,update=False)
            with patch.object(flash,'ask',side_effect=[choice,'"a path/transaction.json"']):
                result=flash.choose_install_action(a)
            self.assertEqual(result, field is not None)
            self.assertEqual([k for k,v in vars(a).items() if v], [field] if field else [])
            if field=='resume_part':self.assertEqual(a.resume_part,'a path/transaction.json')

    def test_names_and_real_launcher_argument_forwarding(self):
        with tempfile.TemporaryDirectory(prefix='installer entries ') as folder:
            root=Path(folder); source=root/'source'; self.source(source)
            package=root/'package with spaces'; api['assemble'](package,source)
            self.assertFalse((package/'flash.py').exists())
            self.assertFalse((package/'install-part.cmd').exists())
            self.assertTrue((package/'scripts/installer/part-two-stage.py').exists())
            self.assertTrue(all(p.name.isascii() for p in package.rglob('*')))
            output=root/'args.json'
            (package/'OpenWrt-Installer.py').write_text(
                'import sys,json\nfrom pathlib import Path\n'
                f'Path({str(output)!r}).write_text(json.dumps(sys.argv[1:]))\n'
                'raise SystemExit(7)\n')
            extension='cmd' if os.name=='nt' else 'sh'
            for name,flag in api['ACTIONS'].items():
                args=['C:/saved files/transaction.json'] if name=='resume-internal-install' else ['--ssid','a hotspot']
                entry=package/(name+'.'+extension)
                command=['cmd','/d','/c','.\\'+entry.name,*args] if os.name=='nt' else ['sh',str(entry),*args]
                result=subprocess.run(command,input='\n',text=True,capture_output=True,timeout=20,cwd=package)
                self.assertEqual(result.returncode,7,(name,result.stderr,result.stdout))
                self.assertEqual(json.loads(output.read_text()),[flag,*args])

    def test_stale_windows_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'source'; self.source(source)
            (source/'flash.exe').write_bytes(b'old binary')
            (source/'flash-exe.json').write_text(json.dumps({'source_sha256':'0'*64,'binary_sha256':'0'*64}))
            with self.assertRaisesRegex(ValueError,'stale'):
                api['assemble'](root/'package',source)


if __name__=='__main__':unittest.main()
