"""Shared screen transport must ship on both phones, never on the headless UFI."""
from pathlib import Path
import runpy
import tempfile

repo = Path(__file__).resolve().parents[2]
screen = runpy.run_path(str(repo/'devices/t551m/infoscreen/stage.py'))['stage']
headless = runpy.run_path(str(repo/'devices/fm-u20/headless.py'))['clean']
with tempfile.TemporaryDirectory() as tmp:
    for profile in ('t551m', 'e5', 'fm-u20'):
        root = Path(tmp)/profile
        (root/'etc/e5').mkdir(parents=True)
        (root/'etc/e5/device-profile').write_text(profile+'\n')
        (root/'etc/rc.d').mkdir()
        (root/'etc/uci-defaults').mkdir()
        screen(root)
        index = (root/'usr/share/e5-infoscreen/www/index.html').read_text()
        assert index.count('src="transport.js"') == 1
        assert index.index('transport.js') < index.index('calls.js')
        for name in ('e5_call_events.py', 'e5_screen_rpc.py'):
            assert (root/'usr/lib/e5'/name).read_bytes() == (repo/'openwrt/overlay/usr/lib/e5'/name).read_bytes().replace(b'\r\n',b'\n')
        for name in ('calls.js', 'transport.js'):
            assert (root/'usr/share/e5-infoscreen/www'/name).read_bytes() == (repo/'devices/t551m/infoscreen'/name).read_bytes().replace(b'\r\n',b'\n')
        assert b'T551MTransport' in (root/'usr/share/e5-infoscreen/www/sdk/e5.js').read_bytes()
        assert b'T551MCalls.subscribe' in (root/'etc/e5-infoscreen/plugins/phone/phone.js').read_bytes()
        assert (root/'etc/e5/device-profile').read_text().strip() == profile
        if profile == 'fm-u20':
            cache=root/'usr/lib/e5/__pycache__';cache.mkdir()
            for stem in ('e5_call_events','e5_screen_rpc'): (cache/(stem+'.cpython-312.pyc')).touch()
            (cache/'sms_pdu.cpython-312.pyc').touch()
            headless(root);headless(root)
            for name in ('usr/share/e5-infoscreen','usr/libexec/e5-voice-audio',
                         'usr/lib/e5/e5_call_events.py','usr/lib/e5/e5_screen_rpc.py',
                         'etc/init.d/e5-infoscreen','etc/init.d/e5-voice-audio'):
                assert not (root/name).exists(), name
            assert list(cache.iterdir()) == [cache/'sms_pdu.cpython-312.pyc']
            assert not list((root/'etc/rc.d').glob('*e5-hfp'))
print('E5/T551M shared event/read transport and idempotent headless exclusion PASS')
