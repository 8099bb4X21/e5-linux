#!/usr/bin/env python3
"""Idempotent FM-only cleanup; keep the shared modem/SMS and BlueZ managers."""
import argparse
import json
import os
from pathlib import Path
import shutil

SERVICES = ('e5-infoscreen', 't551m-screen-power', 'e5-charge-mode', 'e5-charge',
            'e5-voice-audio', 'e5-pulseaudio', 'e5-audio', 'e5-bt', 'e5-hfp')
REMOVED = [
    'lib/upgrade/keep.d/t551m-screen', 'etc/config/e5-audio', 'etc/config/e5-charge',
    'etc/config/e5-infoscreen', 'etc/e5-infoscreen', 'usr/share/e5-infoscreen',
    'usr/share/e5-charge', 'etc/pulse',
    'usr/libexec/e5-hfp', 'usr/libexec/e5-volume', 'usr/libexec/e5-call-volume',
    'usr/libexec/e5-voice-audio', 'usr/libexec/e5-bt-connect', 'usr/libexec/e5-bt-check',
    'usr/lib/e5/e5_call_events.py', 'usr/lib/e5/e5_screen_rpc.py',
    'usr/libexec/e5-charge', 'usr/libexec/e5-charge-mode', 'usr/libexec/e5-charge-screen',
    'usr/libexec/e5-infoscreen', 'usr/libexec/rpcd/t551m-screen',
    'opt/e5/e5-audio-dsp', 'usr/bin/e5-vibrate',
    'opt/e5/e5-call-audio.py', 'usr/libexec/__pycache__',
    'usr/share/rpcd/ucode/e5-sms.uc', 'usr/share/rpcd/acl.d/luci-app-e5-sms.json',
    'usr/share/luci/menu.d/luci-app-e5-sms.json', 'www/luci-static/resources/view/e5-sms',
]
for name in ('e5-infoscreen', 't551m-screen'):
    REMOVED += ['usr/share/rpcd/acl.d/luci-app-'+name+'.json',
                'usr/share/luci/menu.d/luci-app-'+name+'.json']
REMOVED += ['usr/share/rpcd/ucode/e5-infoscreen.uc', 'www/luci-static/resources/view/e5-infoscreen']
REMOVED += ['etc/init.d/'+name for name in SERVICES]

def clean(root):
    root = Path(root).absolute()
    if root == Path('/') or os.name == 'nt' or (root/'etc/e5/device-profile').read_text().strip() != 'fm-u20':
        raise ValueError('Expected an offline FM_U20 root')
    for relative in REMOVED:
        p = root/relative
        if p.is_symlink() or p.is_file(): p.unlink()
        elif p.is_dir(): shutil.rmtree(p)
    cache = root/'usr/lib/e5/__pycache__'
    if cache.is_dir():
        for stem in ('e5_call_events', 'e5_screen_rpc'):
            for p in cache.glob(stem+'.*.pyc'): p.unlink()
    for p in (root/'etc/rc.d').iterdir():
        if p.is_symlink() and any(os.readlink(p).endswith('/'+s) for s in SERVICES): p.unlink()
    for p in (root/'etc/uci-defaults').iterdir():
        if any(key in p.name for key in ('infoscreen', 'charge-mode', 'screen-wallpaper')): p.unlink()
    notify=root/'etc/config/e5-notify'
    if notify.exists():
        text=notify.read_text()
        for key in ('sound','screen','vibrate'):
            text=text.replace("option "+key+" '1'", "option "+key+" '0'")
        notify.write_text(text)
    (root/'etc/e5/feature-port.json').write_text(json.dumps({
        'schema': 2, 'profile': 'fm-u20', 'screen': False, 'battery': False, 'tf_card': False,
        'install_target': 'userdata-image', 'wifi_driver': 'seekwave',
        'bluetooth': 'device-management', 'bluetooth_audio': False, 'docker_preinstalled': False,
        'usb_roles': ['peripheral', 'host', 'auto'], 'usb_host_validation': 'pending-hardware',
        'storage_validation': 'emmc-fault-unresolved',
        'features': ['aurora', 'dashboard', 'dual-sim', 'traffic', 'sms', 'sms-forward',
                     'at-workers', 'pre-dial-replay', 'isolated-nv', 'cpu-frequency',
                     'cpu-boot-voltage', 'thermal', 'leds', 'bluetooth-management',
                     'usb-host-network', 'usb-storage', 'exfat', 'ntfs3', 'kvm', 'container-kernel'],
    }, indent=2)+'\n')

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    clean(ap.parse_args().root)
