#!/usr/bin/env python3
"""荣悦 E5 OpenWrt 一键刷入 / one-click flash of OpenWrt on the Rongyue E5.

  flash.py                  first install onto the **SD card**, from rooted
                            Android over adb: the card is partitioned and
                            formatted, OpenWrt goes onto it
  flash.py --data           the same onto the phone's storage (userdata), the
                            form before the SD card; it asks three times
  flash.py --part           first install onto an internal eMMC partition,
                            without an SD card: the next boot shrinks userdata,
                            creates the partition and writes OpenWrt into it
  flash.py --update         update, from the running e5-linux over the USB LAN
                            (OpenWrt's settings and installed apps kept)
  flash.py --boot-openwrt   from Android back to the installed OpenWrt (adb)
  flash.py --check          the checks and the device's files, from Android, and
                            nothing written (a dry run of the first install)

Options for the first install (asked for when not given):
  --apn APN            the carrier's APN (default: automatic, from the SIM)
  --ssid SSID          the hotspot's name (default: <device model>-OpenWrt)
  --wifi-key KEY       the hotspot's WPA2 key, 8-63 characters (default: random)
  -y                   no questions: the defaults, and yes to erasing the card

Runs on Windows, macOS and Linux with Python 3.8+ and adb (Android
platform-tools).  flash.cmd (Windows) and flash.sh start it.  See README.md.
"""
import argparse
import gzip
import hashlib
import http.server
import json
import os
import random
import re
import runpy
import shutil
import socket
import string
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import struct
import zlib
import uuid  # also bundled for the runtime two-stage installer in flash.exe
from decimal import Decimal, InvalidOperation, ROUND_CEILING

B = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
F = os.path.join(B, 'files')
SCRIPTS = os.path.join(B, 'scripts')
D = '/data/e5linux'
TMP = '/data/local/tmp'

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


STEP = [0, 0]           # [this step, of how many]


def say(msg):
    # "[3/8] ..." while a run counts its steps (steps())
    if STEP[1]:
        STEP[0] += 1
        print(f'\n[{STEP[0]}/{STEP[1]}] ' + msg, flush=True)
    else:
        print('\n== ' + msg, flush=True)


def steps(n):
    STEP[0], STEP[1] = 0, n


def bar(frac, label, extra=''):
    """One line, redrawn: [#########.........]  45%  label  extra"""
    frac = max(0.0, min(1.0, frac))
    w = 28
    fill = int(frac * w)
    sys.stdout.write(f'\r   [{"#" * fill}{"." * (w - fill)}] {frac * 100:3.0f}%  {label}  {extra}   ')
    sys.stdout.flush()
    if frac >= 1.0:
        sys.stdout.write('\n')


class busy:
    """A running clock while something slow happens on the device."""
    def __init__(self, label):
        self.label = label
        self.done = threading.Event()
        self.failed = False

    def _run(self):
        t0 = time.time()
        spin = '|/-\\'
        i = 0
        while not self.done.wait(0.25):
            sys.stdout.write(f'\r   {spin[i % 4]} {self.label}  {int(time.time() - t0)} s   ')
            sys.stdout.flush()
            i += 1
        result = 'FAILED' if self.failed else 'OK'
        sys.stdout.write(f'\r   {result} {self.label}  {int(time.time() - t0)} s          \n')
        sys.stdout.flush()

    def __enter__(self):
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.failed = bool(exc[0])
        self.done.set()
        self.t.join()


def die(msg):
    print('\n错误 / error: ' + msg, file=sys.stderr, flush=True)
    sys.exit(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def gz_usize(path):
    """Check gzip integrity and count its real size (ISIZE wraps at 4 GiB)."""
    size = 0
    try:
        with gzip.open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                size += len(chunk)
    except (OSError, EOFError) as error:
        die(f'cannot decompress {os.path.basename(path)}: {error}')
    if not size:
        die(f'{os.path.basename(path)} contains an empty image')
    return size


def boot_json():
    with open(os.path.join(F, 'boot.json')) as f:
        return json.load(f)


def package_profile():
    path = os.path.join(F, 'device-profile.json')
    if not os.path.isfile(path):
        return None  # Legacy E5 packages did not carry a profile manifest.
    with open(path, encoding='utf-8') as stream:
        value = json.load(stream)
    if value.get('profile') not in ('e5', 't551m', 'm8') or not value.get('android_models'):
        die('invalid package device profile')
    return value


def default_hotspot_name():
    profile = package_profile()
    model = {'e5': 'E5', 't551m': 'T551M', 'm8': 'M8'}[
        profile['profile'] if profile else 'e5']
    return model + '-OpenWrt'


def check_package():
    say('检查刷机包 / checking the package')
    bad = None
    with busy('校验文件 / verifying the files'), open(os.path.join(B, 'SHA256SUMS')) as f:
        for line in f:
            want, name = line.split(None, 1)
            name = name.strip()
            if sha256(os.path.join(B, *name.split('/'))) != want:
                bad = name
                break
    if bad:
        die(f'{bad} is damaged: download the package again')
    with open(os.path.join(F, 'VERSION'), encoding='utf-8') as f:
        print('   ' + f.read().strip())


# ------------------------------------------------------------------ adb

ADB = None
SU = None


def find_adb():
    global ADB
    for c in (shutil.which('adb'), os.path.join(B, 'platform-tools', 'adb.exe'),
              os.path.join(B, 'platform-tools', 'adb')):
        if c and os.path.isfile(c):
            ADB = c
            return
    die('adb not found: install Android platform-tools and put adb in PATH '
        '(or unpack platform-tools next to this script)')


def adb(*args, check=False, capture=True, timeout=600):
    r = subprocess.run([ADB, *args], stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None, timeout=timeout)
    out = r.stdout.decode('utf-8', 'replace').replace('\r', '') if capture else ''
    if check and r.returncode != 0:
        die(f'adb {" ".join(args[:2])} failed: {out.strip()[-300:]}')
    return out


def sh(cmd, timeout=600):
    return adb('shell', cmd, timeout=timeout)


def su(cmd, timeout=600):
    # one argument for adb, one single-quoted string for su: cmd has no '
    assert "'" not in cmd
    return adb('shell', f"{SU} -c '{cmd}'", timeout=timeout)


def su_checked(stage, cmd, timeout=600):
    """Fail at the actual remote stage; adb success alone is insufficient.

    Do not print the command: settings commands can contain private values.
    The subshell's set -e catches earlier failures in a sequence too.
    """
    marker = '__E5_STAGE_STATUS__='
    wrapped = f'(set -e; {cmd}); e5_stage_rc=$?; echo {marker}$e5_stage_rc'
    try:
        out = su(wrapped, timeout=timeout)
    except subprocess.TimeoutExpired:
        die(f'{stage}: timed out after {timeout} seconds; check the device/adb connection')
    except OSError as error:
        die(f'{stage}: cannot run adb: {error}')
    matches = list(re.finditer(r'^' + marker + r'(\d+)\s*$', out, re.M))
    if not matches:
        die(f'{stage}: device returned no completion status (adb disconnected or su failed).\n'
            + out.strip()[-2000:])
    match = matches[-1]
    body = out[:match.start()].rstrip()
    status = int(match.group(1))
    if status:
        try:
            context = su('dmesg | grep -iE "mmc|sdhci|ext4|I/O error|read-only|crc|Buffer I/O" | tail -18', timeout=20)
        except (subprocess.TimeoutExpired, OSError):
            context = '(kernel diagnostics unavailable: device did not respond)'
        die(f'{stage}: failed (exit {status}).\n{body[-3000:]}\n'
            f'SD/filesystem kernel messages:\n{context.strip()[-3000:]}')
    return body


def push(local, remote, label):
    """In pieces, each checked: adb push has no resume."""
    size = os.path.getsize(local)
    want = sha256(local)
    su(f'rm -f {remote}')
    # (16 MiB pieces: a finer bar, and a failed piece costs less)
    part = 16 << 20
    t0 = time.time()
    bar(0, label)
    n = 0
    with open(local, 'rb') as f, tempfile.TemporaryDirectory() as td:
        while True:
            data = f.read(part)
            if not data:
                break
            p = os.path.join(td, f'p{n:03d}')
            with open(p, 'wb') as o:
                o.write(data)
            rp = f'{TMP}/e5-part{n:03d}'
            for _ in range(3):
                adb('push', p, rp)
                if su(f'stat -c %s {rp}').strip() == str(len(data)):
                    break
            else:
                die(f'pushing {label} failed')
            su(f'cat {rp} >> {remote}; rm -f {rp}')
            os.remove(p)
            n += 1
            done = min(n * part, size)
            rate = done / max(time.time() - t0, 0.1) / 1048576
            bar(done / size, label, f'{done >> 20}/{size >> 20} MiB  {rate:.1f} MiB/s')
    with busy('校验 / verifying'):
        ok = su(f'sha256sum {remote}').split()[0:1] == [want]
    if not ok:
        die(f'{label} arrived damaged')


def od_hex(path_or_cmd):
    return su(f'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1 -v').replace(' ', '').replace('\n', '')


def arm_slot_b():
    # Derive metadata from this device, not the package author's misc snapshot.
    before = read_boot_control()
    trial = bytearray(before)
    trial[:4] = b'_b\0\0'
    trial[12] = (before[12] & 0xf0) | 14
    trial[14] = 0x2f
    trial[28:] = struct.pack('<I', zlib.crc32(trial[:28]))
    with tempfile.TemporaryDirectory() as work:
        local = os.path.join(work, 'trial.bin')
        with open(local, 'wb') as stream:
            stream.write(trial)
        push(local, f'{TMP}/e5-bc-b.bin', 'boot control')
    expected = hashlib.sha256(before).hexdigest()
    wanted = hashlib.sha256(trial).hexdigest()
    command = (
        'umask 077; mkdir -p /data/adb/e5-boot-control; '
        'backup=$(mktemp /data/adb/e5-boot-control/before.XXXXXX); '
        'dd if=/dev/block/by-name/misc of="$backup" bs=1 skip=2048 count=32; '
        f'[ "$(sha256sum "$backup" | cut -d " " -f1)" = {expected} ]; sync; '
        'if dd if=/data/local/tmp/e5-bc-b.bin of=/dev/block/by-name/misc '
        'bs=1 seek=2048 count=32 conv=notrunc,fsync && '
        f'[ "$(dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | sha256sum | cut -d " " -f1)" = {wanted} ]; '
        'then echo "Boot control backup: $backup"; '
        'else dd if="$backup" of=/dev/block/by-name/misc bs=1 seek=2048 count=32 conv=notrunc,fsync; '
        f'[ "$(dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | sha256sum | cut -d " " -f1)" = {expected} ] || '
        'echo "RESTORE FAILED: do not reboot; inspect misc and $backup"; exit 1; fi; '
        f'rm -f {TMP}/e5-bc-b.bin')
    print(su_checked('设置 B 槽试启动 / arming slot B', command))


def validate_boot_control(data):
    if (len(data) != 32 or data[4:8] != b'BCAB' or data[8] != 1 or data[9] & 7 != 2
            or struct.unpack('<I', data[28:])[0] != zlib.crc32(data[:28])):
        raise ValueError('invalid BCAB format/version/CRC')
    if not data[12] & 0x80 or not data[12] & 15 or data[13] & 1 or data[15] & 1:
        raise ValueError('Android A is not successful or a slot has a verity error')
    if (data[14] & 15) > (data[12] & 15):
        raise ValueError('B has higher priority: finish or cancel the pending Android OTA first')
    return data


def read_boot_control():
    try:
        return validate_boot_control(bytes.fromhex(od_hex(None)))
    except ValueError as error:
        die(f'boot control check failed: {error}')


def bootchain(mode):
    if mode not in ('check', 'sync'):
        raise ValueError(mode)
    script = f'{TMP}/e5-android-bootchain.sh'
    push(os.path.join(F, 'android-bootchain.sh'), script, 'boot-chain checks')
    # Absolute BusyBox path avoids Android toybox differences and Magisk PATH.
    result = su_checked('检查启动链 / checking boot chain' if mode == 'check' else
                        '备份并同步启动链 / backing up and syncing boot chain',
                        f'ASH_STANDALONE=1 /data/adb/magisk/busybox sh {script} {mode}', timeout=600)
    print(result)


def install_preflight():
    read_boot_control()
    image = os.path.join(F, 'boot.img')
    if os.path.getsize(image) != device_size('/dev/block/by-name/boot_b'):
        die('boot image/boot_b partition size mismatch; nothing formatted')
    if sha256(image) != boot_json()['sha256']:
        die('boot image does not match boot.json')
    bootchain('check')


def android_checks():
    global SU
    say('连接设备 / looking for Android (USB debugging on)')
    devs = [l for l in adb('devices').splitlines()[1:] if l.strip().endswith('\tdevice')]
    if len(devs) != 1:
        die(f'need exactly one device in "adb devices" (found {len(devs)}; allow USB debugging on the phone)')
    for s in ('su', '/debug_ramdisk/su', '/sbin/su'):
        if 'uid=0' in sh(f'{s} -c id'):
            SU = s
            break
    if not SU:
        die('no root: install Magisk and grant Shell superuser access')
    profile = package_profile()
    if profile:
        model = sh('getprop ro.product.model').strip()
        if model not in profile['android_models']:
            die(f"Wrong device: package is for {profile['profile']}, Android reports {model!r}. Nothing was written.")
    if sh('getprop ro.boot.slot_suffix').strip() != '_a':
        die('Android is not running from slot a')
    if sh('getprop ro.boot.verifiedbootstate').strip() != 'orange':
        die('the bootloader is locked (verifiedbootstate is not orange)')
    if 'ok' not in su('[ -e /dev/block/by-name/boot_b ] && [ -e /dev/block/by-name/l_agdsp_a ] && echo ok'):
        die('no boot_b or l_agdsp_a partition: not an E5?')
    su_checked('检查 Magisk 工具 / checking Magisk tools', 'test -x /data/adb/magisk/busybox')
    print(f'   ok ({sh("getprop ro.product.model").strip()}, root via {SU})')


# ------------------------------------------------------ the device's files

def pull_device_files(work, out=None):
    """The firmware off Android, converted here; the vendor subset collected
    and everything packed on the device (collect-device-files.sh), into out
    (the install's device-files.tar by default)."""
    out = out or f'{D}/device-files.tar'
    say('从这台设备提取固件和基带文件 / the firmware and baseband files of this device')
    st = f'{TMP}/e5pull'
    su(f'rm -rf {st}; mkdir -p {st}')
    wanted = ['/odm/firmware/wcnmodem.bin', '/odm/firmware/gnssmodem.bin',
              '/odm/firmware/bt_configure_pskey.xpe.ini', '/odm/firmware/bt_configure_rf.xpe.ini',
              '/mnt/vendor/btmac.txt', '/vendor/firmware/aw87xxx_acf.bin',
              '/odm/etc/audio_params/sprd/audio_structure.xml',
              '/odm/etc/audio_params/sprd/codec.xml',
              '/odm/etc/audio_params/sprd/dsp_vbc.xml', '/odm/etc/audio_params/sprd/cvs.xml']
    wanted += ['/odm/firmware/' + n for n in su('ls /odm/firmware/').split()
               if n.startswith('wifi_board_config') and n.endswith('.ini')]
    for p in wanted:
        su(f'cp -f {p} {st}/ 2>/dev/null')
    # optional on some units (a dangling link on this one)
    su(f'cp -f /vendor/firmware/tsx_data {st}/ 2>/dev/null')
    su(f'dd if=/dev/block/by-name/l_agdsp_a of={st}/l_agdsp_a.img bs=1M count=6 2>/dev/null; chmod -R a+r {st}')
    raw = os.path.join(work, 'raw')
    os.makedirs(raw)
    names = su(f'ls {st}').split()
    for i, n in enumerate(names):
        adb('pull', f'{st}/{n}', os.path.join(raw, n), check=True)
        bar((i + 1) / len(names), '固件 / firmware', n)
    su(f'rm -rf {st}')
    need = ['wcnmodem.bin', 'bt_configure_pskey.xpe.ini', 'bt_configure_rf.xpe.ini', 'btmac.txt',
            'l_agdsp_a.img', 'audio_structure.xml', 'dsp_vbc.xml', 'cvs.xml']
    for n in need:
        if not os.path.isfile(os.path.join(raw, n)):
            die(f'this device has no {n}: not an E5, or a different firmware')
    img = os.path.join(raw, 'l_agdsp_a.img')
    with open(img, 'rb') as f:
        head = f.read(11)
    if os.path.getsize(img) < 6291456 or not head.startswith(b'SharkL5_AUD'):
        die('the audio DSP image (l_agdsp_a) is not the expected one')

    fw = os.path.join(work, 'lib', 'firmware')
    os.makedirs(os.path.join(fw, 'sprd'))
    for n in os.listdir(raw):
        if n in ('wcnmodem.bin', 'gnssmodem.bin', 'aw87xxx_acf.bin', 'tsx_data', 'l_agdsp_a.img', 'codec.xml') or \
                (n.startswith('wifi_board_config') and n.endswith('.ini')):
            shutil.copy(os.path.join(raw, n), fw)
    tools = os.path.join(SCRIPTS, 'tools')
    subprocess.run(python_tool(os.path.join(tools, 'sprd-bt-config.py'),
                    os.path.join(raw, 'bt_configure_pskey.xpe.ini'), os.path.join(raw, 'bt_configure_rf.xpe.ini'),
                    os.path.join(raw, 'btmac.txt'), os.path.join(fw, 'sprd')), check=True)
    subprocess.run(python_tool(os.path.join(tools, 'vbc-profile', 'vbc-profile.py'),
                    os.path.join(raw, 'dsp_vbc.xml'), os.path.join(raw, 'audio_structure.xml'),
                    os.path.join(raw, 'cvs.xml'), '-o', fw), check=True, stdout=subprocess.DEVNULL)
    for n in ('sprd/marlin3lite_pskey.bin', 'sprd/marlin3lite_rf.bin', 'audio_structure', 'dsp_vbc', 'cvs'):
        if not os.path.isfile(os.path.join(fw, *n.split('/'))):
            die(f'converting the firmware made no {n}')

    def root(t):
        t.uid = t.gid = 0
        t.uname = t.gname = 'root'
        t.mode = (t.mode | 0o644) if t.isfile() else (t.mode | 0o755)
        return t
    fwtar = os.path.join(work, 'firmware.tar')
    with tarfile.open(fwtar, 'w', format=tarfile.GNU_FORMAT) as t:
        t.add(os.path.join(work, 'lib'), 'lib', filter=root)
    adb('push', fwtar, f'{TMP}/e5-firmware.tar', check=True)
    adb('push', os.path.join(F, 'collect-device-files.sh'), f'{TMP}/e5-collect.sh', check=True)
    with busy('在手机上打包 vendor 文件 / packing the vendor files on the phone'):
        res = su(f'mkdir -p {os.path.dirname(out)}; sh {TMP}/e5-collect.sh {out} {TMP}/e5-firmware.tar; rm -f {TMP}/e5-collect.sh')
    if 'E5-COLLECT-OK' not in res:
        die('collecting the device files failed: ' + res.strip()[-300:])
    return res.split('E5-COLLECT-OK')[-1].strip()


# ------------------------------------------------------------------ modes

def python_tool(*argv):
    """A command that runs one of the package's helper scripts.

    Frozen (flash.exe) there is no Python on the machine, so the executable
    re-enters itself: --run-tool executes the bundled script with its own
    interpreter and passes the remaining arguments through.
    """
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--run-tool', *argv]
    return [sys.executable, argv[0], *argv[1:]]


def ask(prompt, default=''):
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ''
    return v or default


def confirm(prompt, word='yes'):
    """A typed confirmation: anything but the word is a no."""
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ''
    return v.lower() == word


def device_sd():
    """The removable card's block device: the mmcblk device that is not the one
    Android's partitions live on (userdata, misc).  "Removable" cannot be asked
    of this controller -- both mmcblk devices report 0 -- so it is told apart by
    what it carries."""
    emmc = ''
    for line in su('for u in /sys/class/block/mmcblk*p*/uevent; do '
                   'grep -qx PARTNAME=userdata "$u" 2>/dev/null && '
                   'n=${u%/*} && n=${n##*/} && echo ${n%%p*}; done').split():
        emmc = line
        break
    if not emmc:
        die('no userdata partition: not an E5?')
    devs = [d for d in su('for d in /sys/class/block/mmcblk*; do n=${d##*/}; '
                          'case $n in *p[0-9]*|*boot*) continue;; esac; '
                          f'[ $n = {emmc} ] && continue; echo $n; done').split()
            if d.startswith('mmcblk')]
    if len(devs) != 1:
        die('expected one SD card, found %d (%s): is a card in the slot?'
            % (len(devs), ' '.join(devs) or 'none'))
    return '/dev/block/' + devs[0]


def device_size(dev):
    out = su_checked(f'读取容量 / reading capacity of {dev}', 'blockdev --getsize64 %s' % dev).strip()
    if not out.isdigit() or int(out) <= 0:
        die(f'cannot determine the capacity of {dev}: {out!r}')
    return int(out)


def sd_device_numbers(dev):
    name = dev.rsplit('/', 1)[-1]
    out = su_checked('读取 SD 分区设备号 / reading SD device numbers',
                     f'for p in /sys/class/block/{name} /sys/class/block/{name}p*; do '
                     '[ -f "$p/dev" ] && cat "$p/dev"; done; true')
    numbers = {line.strip() for line in out.splitlines() if re.fullmatch(r'\d+:\d+', line.strip())}
    if not numbers:
        die(f'cannot read SD block device numbers for {dev}; refusing to change its partition table')
    return numbers


def unmount_android_sd(dev):
    """After erase confirmation, ask vold to release only this card's volumes."""
    numbers = sd_device_numbers(dev)
    volumes = su_checked('检查 Android SD 卷 / checking Android SD volumes', 'sm list-volumes all')
    for line in volumes.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].split(':', 1)[-1].replace(',', ':') in numbers and fields[1] == 'mounted':
            volume = fields[0]
            if not re.fullmatch(r'(public|private):\d+,\d+', volume):
                continue
            su_checked(f'卸载 Android SD 卷 / unmounting {volume}', f'sm unmount {volume}')
    # mountinfo uses major:minor, while vold names volumes major,minor.
    remaining = []
    for line in su_checked('检查 SD 卸载结果 / checking SD mounts',
                           'cat /proc/self/mountinfo /proc/1/mountinfo').splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[2] in numbers:
            remaining.append(fields[4])
    if remaining:
        die(f'{dev} is still mounted at {", ".join(remaining)}. '
            'Unmount the SD volume in Android storage settings (leave the card inserted) '
            'and retry. The partition table was not changed.')


def install_sd(a):
    """The default first install: OpenWrt onto the SD card.

    The card is partitioned (GPT, one Linux partition) and the generic OpenWrt
    image is written onto the partition -- the partition *is* the filesystem, so
    boot/init mounts it directly (the marked card, /etc/e5/sd-root) instead of a
    file on userdata.  The device's own firmware is unpacked into it, so the
    card carries the whole system and userdata is not the root's home. The
    differing B-slot boot chain is backed up and synchronized from Android A;
    boot_b and the boot target/control are committed after root verification."""
    steps(9)
    find_adb()
    android_checks()
    bj = boot_json()
    install_preflight()
    sd = device_sd()
    capacity = device_size(sd)
    img = os.path.join(F, 'openwrt.ext4.gz')
    raw_size = gz_usize(img)
    needed = raw_size + (2 << 20) + 34 * 512
    if capacity < max(needed, 2 << 30):
        die(f'SD capacity is insufficient: {sd} has {capacity / (1 << 20):.1f} MiB; '
            f'image/GPT/alignment require {needed / (1 << 20):.1f} MiB '
            '(minimum supported card: 2048 MiB). Nothing was written.')
    readonly = su_checked('检查 SD 只读状态 / checking card write protection',
                          f'cat /sys/class/block/{sd.rsplit("/", 1)[-1]}/ro').strip()
    if readonly != '0':
        die(f'{sd} is read-only (ro={readonly}); cannot install. Nothing was written.')

    apn, ssid, key = a.apn, a.ssid if a.ssid is not None else default_hotspot_name(), a.wifi_key
    if not a.y:
        if apn is None:
            apn = ask('APN [自动识别 / automatic, from the SIM]: ')
        ssid = ask(f'热点名称 / hotspot name [{ssid}]: ', ssid)
        if not key:
            key = ask('热点密码 / hotspot key, 8-63 characters [random]: ')
    apn = apn or ''
    if not key:
        key = ''.join(random.SystemRandom().choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(10))
    if not 8 <= len(key) <= 63 or "'" in key or "'" in ssid or "'" in apn:
        die("the hotspot key must have 8-63 characters, and no ' anywhere")

    say(f'准备 SD 卡 / preparing the card ({sd})')
    print(f'   {sd}  {device_size(sd) >> 30} GiB')
    if not a.y:
        print('   OpenWrt 会装到这张卡上，卡上现有的数据会全部丢失。')
        print('   OpenWrt goes onto this card and everything on it is erased.')
        if not confirm('   输入 yes 继续 / type yes to continue: '):
            die('aborted: nothing was written, the card is untouched')

    with tempfile.TemporaryDirectory() as work:
        # Complete firmware conversion and upload all payloads BEFORE erasing
        # the card. A missing vendor file must not destroy a working SD install.
        size = pull_device_files(work, f'{TMP}/e5-device-files.tar')
        push(img, f'{TMP}/openwrt.ext4.gz', 'openwrt.ext4.gz')
        push(os.path.join(F, 'boot.img'), f'{TMP}/e5-boot.img', 'boot.img')
        su_checked('检查 SD 分区工具 / checking partition tools',
                   'command -v sgdisk >/dev/null; command -v blockdev >/dev/null')
        say(f'分区并格式化 / partitioning and formatting the card')
        unmount_android_sd(sd)
        bootchain('sync')
        # The root partition is only as large as the image: the rest of the card
        # stays free, for more systems (another partition the initramfs can be
        # pointed at) and a persistent store of its own.  So the filesystem is
        # not grown to the card -- it fills the partition exactly as built.
        sec = (raw_size + 511) // 512 + 2048       # a MiB of slack past it
        su_checked('清理 GPT / clearing partition table', f'sgdisk --zap-all {sd}')
        su_checked('建立 SD 根分区 / creating root partition',
                   f'sgdisk --new=1:0:+{sec} --typecode=1:8300 --change-name=1:e5root {sd}')
        su_checked('刷新 SD 分区表 / refreshing kernel partition table', f'blockdev --rereadpt {sd}')
        part = sd + 'p1'
        for _ in range(20):
            if 'ok' in su(f'[ -b {part} ] && echo ok'):
                break
            time.sleep(1)
        else:
            details = su(f'ls -l {sd}*; cat /proc/partitions; dmesg | grep -iE "mmc|sdhci|error|crc" | tail -15')
            die(f'{part} did not appear within 20 seconds after partitioning.\n{details}')
        actual_size = device_size(part)
        if actual_size < raw_size or actual_size != sec * 512:
            die(f'{part} has an unexpected size: {actual_size} bytes; expected {sec * 512}. '
                'The kernel may still hold the old partition table; no image was written.')

        say('写入 OpenWrt / OpenWrt -> the card')
        with busy('解压到 SD 卡 / unpacking onto the card'):
            su_checked('解压并写入 SD / decompressing image onto card',
                       f'gzip -dc {TMP}/openwrt.ext4.gz > {part}; sync', timeout=1800)
        su(f'rm -f {TMP}/openwrt.ext4.gz')
        # (no e2fsck here: the image is built by a newer e2fsprogs than the
        # device's, whose feature set -- metadata_csum_seed, orphan_file -- the
        # device's e2fsck calls an error.  The mount below is the check.)

        say('这台设备的文件和首次启动设置 / this device\'s files and the first boot\'s settings')
        conf = os.path.join(work, 'install.conf')
        with open(conf, 'w', newline='\n') as f:
            f.write('# the flash package (flash.py), for OpenWrt\'s first boot\n'
                    f"E5_APN='{apn}'\nE5_WIFI_SSID='{ssid}'\nE5_WIFI_KEY='{key}'\n"
                    "E5_WIFI_CHANNEL='149'\nE5_DEFAULT_BOOT='linux'\n")
        mark = os.path.join(work, 'sd-root')
        with open(mark, 'w', newline='\n') as f:
            f.write('e5-openwrt-sd %s %s\n' % (time.strftime('%Y-%m-%d'), bj['sha256'][:12]))
        adb('push', conf, f'{TMP}/e5-install.conf', check=True)
        adb('push', mark, f'{TMP}/e5-sd-root', check=True)
        m = f'{TMP}/e5sd'
        su(f'umount {m} 2>/dev/null')
        su_checked('挂载 SD 根分区 / mounting root partition',
                   f'mkdir -p {m}; mount -t ext4 {part} {m}')
        with busy('在卡上写设置和设备文件 / writing the settings and the device files'):
            su_checked('写入设置和设备固件 / writing settings and device firmware',
               f'mkdir -p {m}/etc/e5; '
               f'mv {TMP}/e5-install.conf {m}/etc/e5/install.conf; '
               f'chmod 600 {m}/etc/e5/install.conf; '
               f'mv {TMP}/e5-sd-root {m}/etc/e5/sd-root; '
               f'tar -xf {TMP}/e5-device-files.tar -C {m}; '
               f'sha256sum {TMP}/e5-device-files.tar | cut -c1-64 > {m}/etc/e5/device-files.stamp; '
               'sync', timeout=900)
        checksums = f'{TMP}/e5-sd-files.sha256'
        su_checked('记录固件校验 / hashing installed firmware',
                   f'chroot {m} /bin/busybox find /lib/firmware /opt/e5/android -type f '
                   f'-exec /bin/busybox sha256sum {{}} \\; > {checksums}; test -s {checksums}', timeout=900)
        # Reopen after a real unmount; noload avoids writing journal state while
        # verifying. Do not arm B based only on files in the writable mount.
        su_checked('只读重新挂载 SD / reopening card read-only',
                   f'sync; umount {m}; blockdev --flushbufs {part}; mount -t ext4 -o ro,noload {part} {m}')
        # Resolve absolute symlinks in the image's root, not Android's root.
        su_checked('检查镜像用户空间 / checking image userspace', f'chroot {m} /bin/busybox true')
        su_checked('回读校验固件 / verifying firmware after remount',
                   f'chroot {m} /bin/busybox sha256sum -c < {checksums}', timeout=900)
        missing = []
        for name in ('sbin/init', 'lib/firmware/wcnmodem.bin', 'opt/e5/android/vendor/bin/modem_control',
                     'etc/e5/install.conf', 'etc/e5/sd-root'):
            test = f'if ! chroot {m} /bin/busybox test -s /{name}; then echo missing-or-empty:/{name}; '
            if name in ('sbin/init', 'opt/e5/android/vendor/bin/modem_control'):
                test += f'elif ! chroot {m} /bin/busybox test -x /{name}; then echo not-executable:/{name}; '
            result = su_checked(f'检查 SD 文件 / checking /{name}', test + 'fi')
            if result:
                missing.append(result)
        if missing:
            details = su(f'df -h {m}; df -i {m}; mount | grep {m}; '
                         f'ls -ld {m}/sbin/init {m}/lib/firmware {m}/opt/e5/android/vendor/bin/modem_control')
            su(f'umount {m}')
            die(f'SD content verification failed on {part}:\n' + '\n'.join(missing) + '\n' + details)
        su_checked('卸载并同步 SD / unmounting card', f'sync; umount {m}')
        su(f'rm -f {TMP}/e5-device-files.tar {checksums}')
        print(f'   OpenWrt and {size} bytes of device files are on the card')
        free = device_size(sd) - device_size(part)
        print(f'   {free >> 30}.{(free % (1 << 30)) * 10 // (1 << 30)} GiB of the card '
              'are left free, for more partitions (systems, a store)')

        say('写入启动镜像 / boot image -> boot_b')
        with busy('写入并校验 boot_b / writing and verifying boot_b'):
            su_checked('写入 boot_b / writing boot_b',
                       f'dd if={TMP}/e5-boot.img of=/dev/block/by-name/boot_b bs=4M; sync')
            ok = su('sha256sum /dev/block/by-name/boot_b').split()[0:1] == [bj['sha256']]
        if not ok:
            die('boot_b did not verify; Android stays as it is')
        su(f'rm -f {TMP}/e5-boot.img')

    # The boot target, explicit: e5linux/boot-os on userdata is a few bytes, and
    # it is what makes a later `--data` install win over the card again.  The root
    # filesystem itself is not on userdata. Require recording the selector
    # before arming B, rather than leaving an older userdata image selected.
    su_checked('记录 SD 启动目标 / saving SD boot target',
               f'mkdir -p {D}; rm -f {D}/boot-os-next; echo sd > {D}/boot-os; sync')
    arm_slot_b()

    say('安装完成，请手动重启进入 OpenWrt / installed; reboot manually to enter OpenWrt')
    print(f'''
  第一次启动约 2 分钟 / the first boot takes about 2 minutes.
  OpenWrt 在 SD 卡上 / OpenWrt is on the SD card ({sd}p1).
  热点 / hotspot:  {ssid}   密码 / key:  {key}
  管理 / admin:    http://192.168.9.1  (LuCI, root / root -- 请改密码 / change it)
  回 Android:      屏幕 高级 -> 系统 -> 下次启动 Android, or: e5-next-boot android; reboot
  若启动失败，设备会在两次尝试后自动回到 Android。
  If the boot fails, the E5 falls back to Android after two tries.''')

DATA_RESERVE = 1 << 30
DATA_FIRMWARE_BUDGET = 512 << 20
DATA_ALIGNMENT = 1 << 20


def userdata_free():
    avail = su_checked('读取 userdata 可用空间 / reading userdata free space',
                       'df -k /data | tail -1').split()
    if len(avail) < 4 or not avail[3].isdigit():
        die('cannot read free space on /data')
    return int(avail[3]) * 1024


def ensure_userdata_space(selected, free, uploads):
    if selected + DATA_RESERVE + DATA_FIRMWARE_BUDGET + uploads > free:
        die('userdata free space is insufficient for the new image, temporary payloads and '
            '1 GiB Android reserve. Existing images are not deleted. Nothing was armed.')


def choose_userdata_size(a, raw_size, free, uploads):
    minimum = ((raw_size + DATA_ALIGNMENT - 1) // DATA_ALIGNMENT) * DATA_ALIGNMENT
    maximum = ((free - DATA_RESERVE - DATA_FIRMWARE_BUDGET - uploads) // DATA_ALIGNMENT) * DATA_ALIGNMENT
    print(f'   userdata 可用 / free: {free / (1 << 30):.2f} GiB; '
          f'镜像范围 / image range: {minimum / (1 << 30):.2f}–{maximum / (1 << 30):.2f} GiB')
    print('   保留至少 1 GiB 给 Android，并预留上传/固件空间；已有系统镜像不计作可回收空间。')
    if maximum < minimum:
        die('not enough userdata space for the image and safety reserve')
    value = getattr(a, 'image_size', None)
    if value is None and not a.y:
        value = ask(f'镜像大小（GiB，可输入 4 或 6.5）/ image size '
                    f'[{minimum / (1 << 30):g}]: ', str(minimum / (1 << 30)))
    if value is None:
        return minimum
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            raise ValueError()
        selected = int((amount * (1 << 30) / DATA_ALIGNMENT).to_integral_value(rounding=ROUND_CEILING)) * DATA_ALIGNMENT
    except (InvalidOperation, ValueError, OverflowError):
        die('image size must be a positive number in GiB, for example 4 or 6.5')
    if not minimum <= selected <= maximum:
        die(f'image size is outside the permitted range ({minimum / (1 << 30):g}–'
            f'{maximum / (1 << 30):.3f} GiB)')
    ensure_userdata_space(selected, free, uploads)
    return selected


def stage_userdata_image(raw_size, selected):
    if raw_size % DATA_ALIGNMENT or selected % DATA_ALIGNMENT:
        die('userdata image sizes must be aligned to MiB')
    raw_mib, selected_mib = raw_size // DATA_ALIGNMENT, selected // DATA_ALIGNMENT
    if not 0 < raw_mib <= selected_mib <= 2147483647:
        die('userdata image size is outside the supported MiB range')
    script = os.path.join(F, 'userdata-image.sh')
    push(script, f'{TMP}/e5-userdata-image.sh', 'userdata-image.sh')
    su_checked('扩容和只读检查 userdata 镜像 / resizing and verifying userdata image',
               f'sh {TMP}/e5-userdata-image.sh {raw_size} {selected} {raw_mib} {selected_mib}', timeout=1800)


def install(a):
    # checks, device files, OpenWrt, settings, boot image, reboot
    steps(6)
    find_adb()
    android_checks()
    bj = boot_json()
    install_preflight()
    img = os.path.join(F, 'openwrt.ext4.gz')
    raw_size = gz_usize(img)
    selected = choose_userdata_size(a, raw_size, userdata_free(),
                                    os.path.getsize(img) + os.path.getsize(os.path.join(F, 'boot.img')))
    tools = os.path.join(F, 'ext4-tools.tar')
    if not os.path.isfile(tools):
        die('missing ext4-tools.tar: use the updated userdata installer package')
    su_checked('检查已有安装和待提交升级 / checking existing install and pending upgrade',
               f'test ! -L {D}; test ! -L {D}/openwrt.ext4; '
               f'test ! -e {D}/openwrt.ext4.part; test ! -L {D}/openwrt.ext4.part; '
               f'test ! -e {D}/openwrt.ext4.new; test ! -L {D}/openwrt.ext4.new')
    if not a.y:
        say("安装到 userdata（旧方式）/ installing to the phone's storage (userdata)")
        print(f'   OpenWrt 镜像 / image: {selected / (1 << 30):.2f} GiB, /data/e5linux/openwrt.ext4')
        print('   不格式化 userdata；安装完成后手动重启。已有镜像会保留为备份。')
        print('   userdata is not formatted; an existing image is kept as a backup. Reboot manually.')
        for n in (1, 2, 3):
            if not confirm(f'   确认 {n}/3 -- 输入 yes 继续 / type yes to continue: '):
                die('aborted: nothing was written')

    apn, ssid, key = a.apn, a.ssid if a.ssid is not None else default_hotspot_name(), a.wifi_key
    if not a.y:
        if apn is None:
            apn = ask('APN [自动识别 / automatic, from the SIM]: ')
        ssid = ask(f'热点名称 / hotspot name [{ssid}]: ', ssid)
        if not key:
            key = ask('热点密码 / hotspot key, 8-63 characters [random]: ')
    apn = apn or ''
    if not key:
        key = ''.join(random.SystemRandom().choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(10))
    if not 8 <= len(key) <= 63 or "'" in key or "'" in ssid or "'" in apn:
        die("the hotspot key must have 8-63 characters, and no ' anywhere")

    with tempfile.TemporaryDirectory() as work:
        firmware = f'{TMP}/e5-data-device-files.tar'
        size = pull_device_files(work, firmware)
        print(f'   device-files.tar: {size} bytes')
        push(img, f'{TMP}/openwrt.ext4.gz', 'openwrt.ext4.gz')
        push(os.path.join(F, 'boot.img'), f'{TMP}/e5-boot.img', 'boot.img')
        push(tools, f'{TMP}/e5-ext4-tools.tar', 'ext4-tools.tar')
        # Recheck after uploads/firmware collection, so Android concurrent writes
        # cannot turn the initial capacity estimate into a partial installation.
        ensure_userdata_space(selected, userdata_free(), 0)

        say(f'写入 OpenWrt / OpenWrt -> {D}/openwrt.ext4')
        with busy('创建、扩容并检查镜像 / creating, resizing and checking image'):
            stage_userdata_image(raw_size, selected)
        # The completed image was mounted read-only and checked before any
        # boot-chain write. No original Android/NV partition is formatted.
        bootchain('sync')

        say('首次启动设置 / the first boot\'s settings')
        conf = os.path.join(work, 'install.conf')
        with open(conf, 'w', newline='\n') as f:
            f.write('# the flash package (flash.py), for OpenWrt\'s first boot\n'
                    f"E5_APN='{apn}'\nE5_WIFI_SSID='{ssid}'\nE5_WIFI_KEY='{key}'\n"
                    "E5_WIFI_CHANNEL='149'\nE5_DEFAULT_BOOT='linux'\n")
        adb('push', conf, f'{TMP}/e5-install.conf', check=True)
        su_checked('提交用户态镜像 / committing userdata image',
                   f'backup={D}/previous.$(date +%Y%m%d-%H%M%S).$$; '
                   f'if [ -e {D}/openwrt.ext4 ]; then mkdir "$backup"; '
                   f'mv {D}/openwrt.ext4 "$backup/openwrt.ext4"; '
                   f'for n in device-files.tar openwrt-install.conf; do '
                   f'[ ! -e {D}/$n ] || cp -p {D}/$n "$backup/$n"; done; fi; '
                   f'mv {D}/openwrt.ext4.part {D}/openwrt.ext4; '
                   f'mv {firmware} {D}/device-files.tar; '
                   f'mv {TMP}/e5-install.conf {D}/openwrt-install.conf; '
                   f'chmod 600 {D}/openwrt.ext4 {D}/device-files.tar {D}/openwrt-install.conf; sync')

    say('写入启动镜像 / boot image -> boot_b')
    with busy('写入并校验 boot_b / writing and verifying boot_b'):
        su_checked('写入 boot_b / writing boot_b',
                   f'dd if={TMP}/e5-boot.img of=/dev/block/by-name/boot_b bs=4M conv=fsync; sync')
        ok = su('sha256sum /dev/block/by-name/boot_b').split()[0:1] == [bj['sha256']]
    if not ok:
        die('boot_b did not verify; Android stays as it is')
    su(f'rm -f {TMP}/e5-boot.img')
    su_checked('记录 userdata 启动目标 / saving userdata boot target',
               f'rm -f {D}/boot-os-next; echo openwrt > {D}/boot-os; sync')
    arm_slot_b()

    say('安装完成，请手动重启进入 OpenWrt / installed; reboot manually to enter OpenWrt')
    print(f'''
  第一次启动约 2 分钟 / the first boot takes about 2 minutes.
  热点 / hotspot:  {ssid}   密码 / key:  {key}
  管理 / admin:    http://192.168.9.1  (LuCI, root / root -- 请改密码 / change it)
  回 Android:      屏幕 高级 -> 系统 -> 下次启动 Android, or: e5-next-boot android; reboot
  若启动失败，设备会在两次尝试后自动回到 Android。
  If the boot fails, the E5 falls back to Android after two tries.''')


def part_userdata_policy(a):
    """A requested wipe must be explicit, and encryption never implies consent."""
    state = sh('getprop ro.crypto.state').strip()
    kind = sh('getprop ro.crypto.type').strip()
    mounts = su_checked('检查 data 加密 / checking data encryption', 'cat /proc/mounts')
    data_source = next((line.split()[0] for line in mounts.splitlines()
                        if len(line.split()) > 2 and line.split()[1] == '/data'), '')
    encrypted = state == 'encrypted' or kind in ('file', 'block')
    metadata = data_source.startswith(('/dev/block/dm-', '/dev/mapper/'))
    encrypted = encrypted or metadata
    wipe = bool(getattr(a, 'format_userdata', False)) or encrypted
    if encrypted:
        print(f'   检测到 data 加密 / data encryption: {kind or state or "mapped block device"}; '
              '本次安装必须格式化 userdata / formatting userdata is required.')
    elif not a.y and not wipe:
        wipe = confirm('   是否格式化 userdata？这会清空 Android 所有用户数据 / '
                       'format userdata and erase ALL Android user data [no]: ', word='yes')
    if wipe:
        print('   警告 / WARNING: Android 应用、账号、照片及内部存储文件将被清空。')
        print('   ALL Android apps, accounts, photos and internal storage files will be erased.')
        # -y is the existing unattended installer confirmation, not permission
        # for a newly detected destructive operation.
        if a.y and not getattr(a, 'format_userdata', False):
            die('encrypted userdata requires --format-userdata as explicit erase consent; -y alone is insufficient')
    if wipe:
        print('   两阶段安装：重建分区 → 原厂 recovery 清空数据 → Android 重新授权 → 安装 OpenWrt。')
    a.format_userdata = wipe
    return wipe


def part_target(a, raw_size):
    """The userdata node and the sizes an internal-partition install wants."""
    probe = su_checked('读取分区 / reading the partition table',
                       'for u in /sys/class/block/mmcblk*p*/uevent; do '
                       'n=$(basename "$(dirname "$u")"); '
                       'grep -qx PARTNAME=userdata "$u" 2>/dev/null && echo "data $n $(cat /sys/class/block/$n/size)"; '
                       'grep -qx PARTNAME=e5root "$u" 2>/dev/null && echo "part $n"; '
                       'done; df -k /data | tail -1')
    node = data_sectors = ''
    existing = None
    used_mib = 0
    for line in probe.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == 'data':
            node, data_sectors = fields[1], fields[2]
        elif len(fields) >= 2 and fields[0] == 'part':
            existing = fields[1]
        elif len(fields) >= 4 and fields[3].isdigit():
            used_mib = int(fields[2]) // 1024
    if existing:
        die(f'the internal partition {existing} (e5root) already exists; run this installer with '
            '--reinstall-part to write a new system into it (userdata and the partition table stay, '
            'nothing is erased)')
    if not node or not data_sectors.isdigit() or int(data_sectors) == 0:
        die('userdata is not in the partition table of this device')
    udata_mib = int(data_sectors) // 2048
    image_mib = (raw_size + (1 << 20) - 1) // (1 << 20)
    minimum = image_mib + 256
    maximum = udata_mib - (0 if getattr(a, 'format_userdata', False) else used_mib) - 2048
    if maximum < minimum:
        die(f'not enough room: userdata is {udata_mib} MiB with {used_mib} MiB used, '
            f'the image needs a {minimum} MiB partition')
    value = getattr(a, 'part_size', None)
    if value is None and not a.y:
        value = ask(f'内置分区大小（GiB）/ partition size [{((image_mib + 1024) / 1024):.2f}, '
                    f'max {maximum / 1024:.2f}]: ', f'{(image_mib + 1024) / 1024:.2f}')
    if value is None:
        part_mib = min(maximum, ((image_mib + 1024 + 1023) // 1024) * 1024)
    else:
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount <= 0:
                raise ValueError()
            part_mib = int((amount * (1 << 30) / (1 << 20)).to_integral_value(rounding=ROUND_CEILING))
        except (InvalidOperation, ValueError, OverflowError):
            die('the partition size must be a positive number in GiB, for example 4 or 6.5')
    if not minimum <= part_mib <= maximum:
        die(f'partition size outside the permitted range ({minimum / 1024:.2f}–{maximum / 1024:.2f} GiB)')
    return node, udata_mib, used_mib, part_mib


def install_part(a):
    """Install OpenWrt onto its own eMMC partition, in space taken from
    userdata -- without an SD card.  This side only chooses the sizes, stages
    the payloads and arms the boot: the F2FS shrink and the partition table
    change happen on the next boot (boot/install-part.sh in the initramfs),
    where userdata is unmounted and only raw tools touch it."""
    steps(6)
    find_adb()
    android_checks()
    bj = boot_json()
    install_preflight()
    img = os.path.join(F, 'openwrt.ext4.gz')
    raw_size = gz_usize(img)
    wipe = part_userdata_policy(a)
    node, udata_mib, used_mib, part_mib = part_target(a, raw_size)
    data_mib = udata_mib - part_mib
    grow = 1 if a.grow_fs else 0
    if not a.y:
        say("安装到内置分区 / installing to an internal partition")
        print(f'   userdata: {udata_mib / 1024:.2f} -> {data_mib / 1024:.2f} GiB, ' +
              ('清空 Android 用户数据 / erase Android user data' if wipe else 'Android 的文件保留'))
        print(f'   新分区 e5root / new partition: {part_mib / 1024:.2f} GiB（镜像 {raw_size >> 20} MiB）')
        print('   缩容与写入在下次启动由引导镜像完成。')
        print('   The shrink and the writing happen on the next boot, from the boot image;')
        print('   ' + ('userdata WILL BE FORMATTED.' if wipe else 'userdata is not formatted.') +
              ' Reboot manually when done.')
        if not grow and confirm('   完全使用空间：把根文件系统扩满所选分区（默认 2 GiB 分配）/ '
                                'use the whole partition for the system [no]: ', word='yes'):
            grow = 1
        print('   系统分配 / system allocation: ' +
              ('整个分区 / the whole partition' if grow else "镜像大小 / the image's size, about 2 GiB"))
        for n in (1, 2, 3):
            if not confirm(f'   确认 {n}/3 -- 输入 yes 继续 / type yes to continue: '):
                die('aborted: nothing was written')

    apn, ssid, key = a.apn, a.ssid if a.ssid is not None else default_hotspot_name(), a.wifi_key
    if not a.y:
        if apn is None:
            apn = ask('APN [自动识别 / automatic, from the SIM]: ')
        ssid = ask(f'热点名称 / hotspot name [{ssid}]: ', ssid)
        if not key:
            key = ask(f'热点密码 / hotspot key, 8-63 characters [random]: ')
    apn = apn or ''
    if not key:
        key = ''.join(random.SystemRandom().choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(10))
    if not 8 <= len(key) <= 63 or "'" in key or "'" in ssid or "'" in apn:
        die("the hotspot key must have 8-63 characters, and no ' anywhere")

    if wipe:
        part_two_stage('start', a, node, part_mib, data_mib, grow, raw_size, apn, ssid, key)
        return

    with tempfile.TemporaryDirectory() as work:
        firmware = f'{TMP}/e5-data-device-files.tar'
        size = pull_device_files(work, firmware)
        print(f'   device-files.tar: {size} bytes')
        push(img, f'{TMP}/e5-part-install.img.gz', 'openwrt.ext4.gz')
        push(os.path.join(F, 'boot.img'), f'{TMP}/e5-boot.img', 'boot.img')
        conf = os.path.join(work, 'part-install.settings')
        with open(conf, 'w', newline='\n') as f:
            f.write("E5_APN='%s'\nE5_WIFI_SSID='%s'\nE5_WIFI_KEY='%s'\n"
                    "E5_WIFI_CHANNEL='149'\nE5_DEFAULT_BOOT='linux'\n" % (apn, ssid, key))
        adb('push', conf, f'{TMP}/part-install.settings', check=True)
        say(f'落位安装载荷 / staging the install -> {D}')
        su_checked('落位安装载荷 / staging the install',
                   f'umask 077; mkdir -p {D}; '
                   f'mv {TMP}/e5-part-install.img.gz {D}/part-install.img.gz; '
                   f'mv {firmware} {D}/device-files.tar; '
                   f'mv {TMP}/part-install.settings {D}/part-install.settings; '
                   f'printf "PART_MIB={part_mib}\\nDATA_MIB={data_mib}\\nGROW_FS={grow}\\nFORMAT_DATA={int(wipe)}\\n" > {D}/part-install.conf.tmp; '
                   f'mv {D}/part-install.conf.tmp {D}/part-install.conf; '
                   f'chmod 600 {D}/part-install.conf {D}/part-install.settings {D}/device-files.tar; sync')

    bootchain('sync')
    say('写入启动镜像 / boot image -> boot_b')
    with busy('写入并校验 boot_b / writing and verifying boot_b'):
        su_checked('写入 boot_b / writing boot_b',
                   f'dd if={TMP}/e5-boot.img of=/dev/block/by-name/boot_b bs=4M conv=fsync; sync')
        ok = su('sha256sum /dev/block/by-name/boot_b').split()[0:1] == [bj['sha256']]
    if not ok:
        die('boot_b did not verify; Android stays as it is')
    su(f'rm -f {TMP}/e5-boot.img')
    su_checked('记录分区启动目标 / recording the partition boot target',
               f'rm -f {D}/boot-os-next; echo part > {D}/boot-os; sync')
    arm_slot_b()

    say('安装已就绪，请手动重启 / staged; reboot manually')
    print(f'''
  下一次启动由引导镜像完成缩容、建分区并写入 OpenWrt（约几分钟），随后自动重启进入它。
  The next boot shrinks userdata, creates the e5root partition and writes
  OpenWrt into it, then restarts once into it -- about a few minutes.
  热点 / hotspot:  {ssid}   密码 / key:  {key}
  管理 / admin:    http://192.168.9.1  (LuCI, root / root -- 请改密码 / change it)
  回 Android:      e5-next-boot android（或删掉 {D}/boot-os）后重启；首启是试启动，
  失败会回到 Android。If the first boot fails, the next one falls back.''')


def part_two_stage(action, *args):
    try:
        runpy.run_path(os.path.join(B, 'part-two-stage.py'))[action](globals(), *args)
    except (ValueError, OSError) as error:
        die(str(error))


def check(a):
    steps(3)
    find_adb()
    android_checks()
    install_preflight()
    print('   free on /data: ' + su('df -k /data | tail -1').split()[3] + ' KiB')
    # packed as for an install, to see that it works, and deleted again: a
    # check leaves nothing on the device
    with tempfile.TemporaryDirectory() as work:
        size = pull_device_files(work, f'{TMP}/e5-check-device-files.tar')
    su(f'rm -f {TMP}/e5-check-device-files.tar')
    print(f'   device-files.tar: {size} bytes (a trial, deleted again)')
    say('检查完成，未修改分区 / checked; no partitions changed (temporary staging files only)')


def boot_openwrt(a):
    steps(2)
    find_adb()
    android_checks()
    bj = boot_json()
    if 'ok' not in su(f'{{ [ -f {D}/openwrt.ext4 ] || [ "$(cat {D}/boot-os 2>/dev/null)" = sd ]; }} && echo ok'):
        die('OpenWrt is not installed: run the first install')
    mb = bj['persist_log_offset'] // 1048576
    head = su(f'dd if=/dev/block/by-name/boot_b bs=1048576 count={mb} 2>/dev/null | sha256sum').split()[0:1]
    if head != [bj['sha256_head56m']]:
        die('boot_b holds another boot image: use the package it was flashed with, or a first install')
    bootchain('sync')
    # OpenWrt the default again, not only for this boot (the screen's "boot
    # Android" made Android the default); /etc/init.d/e5-boot-ok takes it
    su(f'echo linux > {D}/openwrt-default-boot')
    arm_slot_b()
    say('正在重启进 OpenWrt / rebooting into OpenWrt')
    adb('reboot')


def local_ip(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def update(a):
    host = os.environ.get('E5_HOST', '192.168.9.1')
    try:
        ip = local_ip(host)
    except OSError:
        ip = ''
    if not ip.startswith('192.168.9.') and not ip.startswith('192.168.77.'):
        die("no address on the E5's USB LAN (192.168.9.x): is it connected and running OpenWrt?")
    pw = os.environ.get('E5_TELNET_PASS')
    if pw is None and (a.y or not sys.stdin.isatty()):
        pw = 'root'     # (-y: the default, not asked)
    if pw is None:
        import getpass
        pw = getpass.getpass('root password of the E5 [root]: ') or 'root'
    bj = boot_json()
    profile = package_profile()
    guard = ''
    if profile:
        guard = ('[ "$(cat /etc/e5/device-profile 2>/dev/null)" = ' + profile['profile'] +
                 ' ] || { echo "error: package/device profile mismatch" >&2; exit 1; }\n')
    mb = bj['persist_log_offset'] // 1048576
    with tempfile.TemporaryDirectory() as td:
        head = os.path.join(td, 'boot-head.img')
        with open(os.path.join(F, 'boot.img'), 'rb') as i, open(head, 'wb') as o:
            o.write(i.read(mb << 20))
        files = {'/boot-head.img': head,
                 '/openwrt.ext4.gz': os.path.join(F, 'openwrt.ext4.gz'),
                 '/dii.sh': os.path.join(F, 'device-install-image.sh'),
                 '/e5-gpt': os.path.join(F, 'e5-gpt'),
                 '/dfb.sh': os.path.join(F, 'device-flash-boot.sh')}

        class H(http.server.SimpleHTTPRequestHandler):
            def translate_path(self, path):
                return files.get(path.split('?')[0], os.path.join(td, 'nothing'))

            def log_message(self, *args):
                pass

        srv = http.server.ThreadingHTTPServer((ip, 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        u = f'http://{ip}:{srv.server_address[1]}'
        say(f'更新 / updating {host}')
        env = dict(os.environ, E5_TELNET_HOST=host, E5_TELNET_PASS=pw, E5_TELNET_WAIT='1800')
        telnet = python_tool(os.path.join(SCRIPTS, 'tools', 'e5-telnet.py'))
        # The steps as a script the device fetches: a long command line typed over
        # telnet gets lost (the 80-column pty's line editing), so only a short one is.
        steps_sh = f"""set -e
{guard}\
cd /tmp
wget -q -O dfb.sh {u}/dfb.sh
wget -q -O dii.sh {u}/dii.sh
sh dfb.sh {u}/boot-head.img {bj["sha256_head56m"]} {mb}
if [ -f /etc/e5/sd-root ]; then
    # an SD card system (the default install): the new image goes into the card's
    # other root partition, the next boot is its trial; userdata is not touched
    # (FINDINGS 49)
    wget -q -O e5-gpt {u}/e5-gpt
    E5_IMAGE_SIZE={gz_usize(os.path.join(F, "openwrt.ext4.gz"))} sh dii.sh {u}/openwrt.ext4.gz
    # Updating OpenWrt is an explicit operator choice; make it the persistent
    # SD default after the new slot has verified, rather than leaving Debian
    # selected from an earlier multi-system session.
    e5-os openwrt
else
    # the form on userdata (--data, kept for tests)
    sh dii.sh {u}/openwrt.ext4.gz
    d=/mnt/e5-data/e5linux
    rm -f $d/boot-os-next
    echo openwrt > $d/boot-os
    sync
fi
echo E5-UPDATE-$((1+1))
"""
        with open(os.path.join(td, 'update.sh'), 'w', newline='\n') as f:
            f.write(steps_sh)
        files['/update.sh'] = os.path.join(td, 'update.sh')
        cmd = f'cd /tmp && wget -q -O e5-update.sh {u}/update.sh && sh e5-update.sh'
        # the device's own steps as they happen: the boot image, the unpacking,
        # the settings kept, the device's files
        lines = []
        with subprocess.Popen(telnet + [cmd], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as pr:
            with busy('设备上的更新 / the update on the device'):
                for raw in pr.stdout:
                    line = raw.decode('utf-8', 'replace').replace('\r', '').rstrip('\n')
                    lines.append(line)
                    if line.startswith(('==', 'installed', 'WARNING', 'error', 'the image', '   ')):
                        sys.stdout.write('\r   ' + line + ' ' * 20 + '\n')
                        sys.stdout.flush()
        out = '\n'.join(lines)
        srv.shutdown()
        if 'E5-UPDATE-2' not in out:
            print('\n'.join(out.splitlines()[-20:]))
            die('the update did not finish (the log is above)')
        # the reboot on its own: a session the reboot cuts never sees its end
        env['E5_TELNET_WAIT'] = '20'
        subprocess.run(telnet + ['( (sleep 2; reboot) >/dev/null 2>&1 & )'], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say('完成，设备正在重启 / done, the E5 is rebooting')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--update', action='store_true')
    g.add_argument('--boot-openwrt', action='store_true')
    g.add_argument('--check', action='store_true')
    g.add_argument('--data', action='store_true',
                   help="install to the phone's storage (userdata) as before; the SD card is the default")
    g.add_argument('--part', action='store_true',
                   help="install to an internal eMMC partition, without an SD card; "
                        "the next boot shrinks userdata and creates it")
    g.add_argument('--resume-part', metavar='TRANSACTION_JSON',
                   help='continue the encrypted-data installation after Android setup/root authorization')
    g.add_argument('--reinstall-part', action='store_true',
                   help='rewrite an existing internal partition system: userdata, its filesystem and '
                        'the partition table stay, e5root and boot_b are replaced (no wipe, no stage one)')
    ap.add_argument('--apn')
    ap.add_argument('--ssid', help='hotspot name; defaults to the package device model plus -OpenWrt')
    ap.add_argument('--wifi-key')
    ap.add_argument('--image-size', help='userdata image size in GiB (e.g. 4 or 6.5); requires --data')
    ap.add_argument('--part-size', help='internal partition size in GiB (e.g. 4 or 6.5); requires --part')
    ap.add_argument('--grow-fs', action='store_true',
                    help="let the system's filesystem use the whole partition (default: the image's size)")
    ap.add_argument('--format-userdata', action='store_true',
                    help='erase ALL Android user data before internal-partition installation; requires --part')
    ap.add_argument('-y', action='store_true')
    a = ap.parse_args()
    if a.image_size is not None and not a.data:
        ap.error('--image-size requires --data / install-userdata')
    if a.part_size is not None and not a.part:
        ap.error('--part-size requires --part / install-part')
    if a.grow_fs and not a.part:
        ap.error('--grow-fs requires --part / install-part')
    if a.format_userdata and not a.part:
        ap.error('--format-userdata requires --part / install-part')
    if a.reinstall_part and (a.part or a.format_userdata):
        ap.error('--reinstall-part keeps userdata and the partition table; it is not --part')
    if sys.version_info < (3, 8):
        die('Python 3.8 or newer is needed')
    check_package()
    if a.resume_part:
        part_two_stage('resume', a)
    elif a.reinstall_part:
        part_two_stage('reinstall', a)
    elif a.update:
        update(a)
    elif a.boot_openwrt:
        boot_openwrt(a)
    elif a.check:
        check(a)
    elif a.data:
        install(a)          # the form before the SD card; three confirmations
    elif a.part:
        install_part(a)     # an internal partition; the boot image finishes it
    else:
        install_sd(a)


if __name__ == '__main__':
    # A frozen build has no Python beside it: the executable re-enters itself
    # to run the package's helper scripts with its bundled interpreter.
    if len(sys.argv) > 2 and sys.argv[1] == '--run-tool':
        _tool = sys.argv[2]
        sys.argv = [os.path.basename(_tool), *sys.argv[3:]]
        runpy.run_path(_tool, run_name='__main__')
        sys.exit(0)
    try:
        main()
    except KeyboardInterrupt:
        die('interrupted')
