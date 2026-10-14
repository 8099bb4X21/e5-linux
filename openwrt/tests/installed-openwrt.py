#!/usr/bin/env python3
"""Installed-root switching regressions. Only temporary regular-file fixtures."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

TOP=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('flash',TOP/'openwrt/bundle/flash.py')
flash=importlib.util.module_from_spec(spec);spec.loader.exec_module(flash)


@unittest.skipIf(os.name=='nt','Shell filesystem fixtures run under Linux/WSL')
class Probe(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='installed-root-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.sys=self.root/'sys';self.blocks=self.root/'blocks';self.data=self.root/'data';self.tmp=self.root/'tmp';self.bin=self.root/'bin'
        for directory in (self.sys,self.blocks,self.data,self.tmp,self.bin):directory.mkdir()
        self.partition('mmcblk0p70','userdata')
        (self.sys/'mmcblk0').mkdir()
        (self.blocks/'by-name').mkdir()
        (self.blocks/'by-name/userdata').symlink_to(self.blocks/'mmcblk0p70')
        self.script('mount', '''import json,shutil,sys
from pathlib import Path
args=sys.argv[1:]; dev,dest=map(Path,args[-2:])
with open(dev.parent/'mount.log','a') as log:log.write(json.dumps(args)+'\\n')
source=Path(str(dev)+'.fs')
if not source.is_dir():sys.exit(32)
shutil.copytree(source,dest,dirs_exist_ok=True)
''')
        self.script('umount', '''import shutil,sys
from pathlib import Path
dest=Path(sys.argv[-1])
if (dest/'fail-unmount').exists():sys.exit(1)
for child in dest.iterdir():
 if child.is_dir():shutil.rmtree(child)
 else:child.unlink()
''')

    def script(self,name,body):
        path=self.bin/name;path.write_text('#!/usr/bin/env python3\n'+body);path.chmod(0o755)

    def partition(self,name,label,marker=None):
        node=self.sys/name;node.mkdir();(node/'uevent').write_text('PARTNAME='+label+'\n')
        block=self.blocks/name;block.touch()
        if marker:
            root=Path(str(block)+'.fs');(root/'sbin').mkdir(parents=True);(root/'etc/e5').mkdir(parents=True)
            (root/'sbin/init').write_text('init');(root/'sbin/init').chmod(0o755)
            (root/'etc/openwrt_release').write_text("DISTRIB_ID='OpenWrt'\n")
            (root/'etc/e5'/marker).touch()
        return block

    def checked(self,stage,command,**kwargs):
        self.assertNotIn("'",command,'Commands must obey the Android su single-quoted transport')
        command=command.replace('/sys/class/block',str(self.sys)).replace('/dev/block',str(self.blocks))
        # Emulate the hardware block-node predicate using owned regular files.
        command=command.replace('[ -b "$dev" ]','[ -f "$dev" ]')
        env=dict(os.environ,PATH=str(self.bin)+':'+os.environ['PATH'])
        result=subprocess.run(['sh','-ec',command],capture_output=True,text=True,env=env,timeout=10)
        if result.returncode:raise RuntimeError('probe failed: '+result.stderr)
        return result.stdout

    def probe(self):
        with patch.object(flash,'TMP',str(self.tmp)),patch.object(flash,'D',str(self.data)),patch.object(flash,'su_checked',side_effect=self.checked):
            return flash.installed_openwrt()

    def test_marked_internal_partition_without_userdata_selection_is_installed(self):
        self.partition('mmcblk0p71','e5root','part-root')
        self.assertEqual(self.probe(),'part')
        for record in (self.blocks/'mount.log').read_text().splitlines():
            self.assertIn('ro,noload',json.loads(record))
        self.assertEqual(list(self.tmp.iterdir()),[])

    def test_empty_prepared_partition_and_stale_selector_are_not_installed(self):
        self.partition('mmcblk0p71','e5root')
        (self.data/'boot-os').write_text('part')
        self.assertIsNone(self.probe())

    def test_card_is_detected_without_userdata_marker(self):
        (self.sys/'mmcblk1').mkdir();(self.blocks/'mmcblk1').touch()
        self.partition('mmcblk1p1','linux','sd-root')
        self.assertEqual(self.probe(),'sd')

    def test_selection_is_respected_but_missing_selected_card_falls_back(self):
        self.partition('mmcblk0p71','e5root','part-root')
        (self.data/'openwrt.ext4').write_bytes(b'nonempty image')
        (self.data/'boot-os').write_text('openwrt')
        self.assertEqual(self.probe(),'openwrt')
        (self.data/'boot-os').write_text('sd')
        self.assertEqual(self.probe(),'part')

    def test_empty_userdata_image_is_not_an_installed_root(self):
        (self.data/'openwrt.ext4').touch()
        self.assertIsNone(self.probe())

    def test_foreign_partition_name_and_missing_openwrt_files_are_rejected(self):
        (self.sys/'mmcblk1').mkdir()
        self.partition('mmcblk1p1','e5root','part-root')
        root=self.partition('mmcblk0p71','e5root','part-root')
        Path(str(root)+'.fs/etc/openwrt_release').unlink()
        self.assertIsNone(self.probe())

    def test_unmount_failure_aborts_instead_of_selecting_a_slot(self):
        dev=self.partition('mmcblk0p71','e5root','part-root')
        Path(str(dev)+'.fs/fail-unmount').touch()
        with self.assertRaisesRegex(RuntimeError,'probe failed'):self.probe()


class Switch(unittest.TestCase):
    def test_unrecognized_probe_reply_is_not_treated_as_installed(self):
        with patch.object(flash,'su_checked',return_value='ADB offline'),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):flash.installed_openwrt()

    def run_switch(self,target,head,part_head='partition-head'):
        metadata={'persist_log_offset':56<<20,'sha256_head56m':'normal-head'}
        with contextlib.ExitStack() as stack:
            for name in ('find_adb','android_checks','steps','say'):stack.enter_context(patch.object(flash,name))
            stack.enter_context(patch.object(flash,'boot_json',return_value=metadata))
            stack.enter_context(patch.object(flash,'installed_openwrt',return_value=target))
            stack.enter_context(patch.object(flash,'part_boot_head',return_value=part_head))
            stack.enter_context(patch.object(flash,'su',return_value=head+'  -'))
            chain=stack.enter_context(patch.object(flash,'bootchain'))
            save=stack.enter_context(patch.object(flash,'su_checked'))
            arm=stack.enter_context(patch.object(flash,'arm_slot_b'))
            adb=stack.enter_context(patch.object(flash,'adb'))
            if target is None or head not in ('normal-head','partition-head') or (head=='partition-head' and target!='part'):
                with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):flash.boot_openwrt(None)
                chain.assert_not_called();save.assert_not_called();arm.assert_not_called();adb.assert_not_called()
            else:
                flash.boot_openwrt(None)
                chain.assert_called_once_with('sync');arm.assert_called_once();adb.assert_called_once_with('reboot')
                self.assertIn('echo '+target+' >',save.call_args.args[1])
                self.assertIn('boot-os-next',save.call_args.args[1])

    def test_switch_accepts_normal_and_exact_partition_variant_only(self):
        for target,head in [('part','normal-head'),('part','partition-head'),('sd','normal-head'),
                            ('openwrt','normal-head'),(None,'normal-head'),('part','tampered'),('sd','partition-head')]:
            with self.subTest(target=target,head=head):self.run_switch(target,head)

    def test_partition_variant_hash_uses_the_real_installer_patch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=bytearray(8192);image[:8]=b'ANDROID!';struct.pack_into('<I',image,40,4)
            image[44:1580]=b'loglevel=5 e5.part_v=2'.ljust(1536,b'\0')
            (root/'boot.img').write_bytes(image)
            with patch.object(flash,'F',folder),patch.object(flash,'B',str(TOP/'openwrt/bundle')),patch.object(flash,'SCRIPTS',folder):
                actual=flash.part_boot_head({'persist_log_offset':4096})
            image[44:1580]=b'loglevel=5 e5.part_v=2 e5.root=part'.ljust(1536,b'\0')
            self.assertEqual(actual,hashlib.sha256(image[:4096]).hexdigest())


if __name__=='__main__':unittest.main()
