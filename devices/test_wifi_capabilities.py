#!/usr/bin/env python3
"""Test the real ucode policy in an OpenWrt chroot (Linux root + binfmt).

Usage: test_wifi_capabilities.py /path/to/staged-openwrt-root
"""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(sys.argv[1]).resolve()
module = runpy.run_path(str(Path(__file__).with_name('t551m') / 'network-startup.py'))
with tempfile.TemporaryDirectory(prefix='wifi-cap-test-', dir=ROOT / 'tmp') as temp:
    temp = Path(temp)
    target = temp / 'usr/share/ucode/wifi/hostapd.uc'
    target.parent.mkdir(parents=True)
    target.write_bytes((ROOT / 'usr/share/ucode/wifi/hostapd.uc').read_bytes())
    module['patch_wifi_capabilities'](temp)
    first = target.read_bytes()
    module['patch_wifi_capabilities'](temp)
    assert first == target.read_bytes(), 'not idempotent'
    script = temp / 'test.uc'
    script.write_text('let phy_features = {}, phy_capabilities = {};\nfunction log(s) {}\n' + module['NO_DFS'] + '''
function check(value, message) { if (!value) die(message); }
function channels(list) { return map(list, (c) => ({freq:5000+5*c})); }
function run(channel, mode, freqs, radar, band) {
    radar ??= false;
    band ??= '5g';
    phy_features={radar_detect:radar};
    phy_capabilities={freqs:[...freqs,{freq:5260,radar:true}]};
    let c={band:band,channel:channel,htmode:mode};
    device_no_dfs(c);
    return c;
}
let c=run(52,'VHT80',channels([36,40,44,48]));
check(c.channel==36 && c.htmode=='VHT80','80 MHz fallback');
c=run(52,'HE80',channels([149,153]));
check(c.channel==149 && c.htmode=='HE40','40 MHz fallback');
c=run(52,'VHT80',channels([165]));
check(c.channel==165 && c.htmode=='VHT20','20 MHz fallback');
c=run(52,'HT40',[{freq:5180,no_ir:true},{freq:5745,disabled:true},{freq:5825}]);
check(c.channel==165 && c.htmode=='HT20','NO_IR/disabled exclusion');
c=run(0,'VHT80',channels([36]));
check(c.channel==0 && c.acs_exclude_dfs,'ACS filtering');
c=run(52,'VHT80',channels([36]),true);
check(c.channel==52 && c.htmode=='VHT80','radar-capable driver unchanged');
c=run(6,'HT40',[],false,'2g');
check(c.channel==6 && c.htmode=='HT40','2.4 GHz unchanged');
c=run(36,'VHT80',channels([36,40,44,48]));
check(c.channel==36 && c.htmode=='VHT80','non-DFS selection unchanged');
let rejected=false;
try {run(52,'VHT80',[{freq:5180,no_ir:true},{freq:5745,disabled:true}]);}
catch(e) {rejected=true;}
check(rejected,'must not relax NO_IR if no legal fallback exists');
print('PASS: actual ucode DFS capability/regulatory/width policy\\n');
''')
    def inside(path):
        return '/' + str(path.relative_to(ROOT))
    subprocess.run(['chroot', str(ROOT), '/usr/bin/ucode', inside(script)], check=True)
    wrapper = temp / 'compile.uc'
    wrapper.write_text("import * as hostapd from '" + inside(target) + "';\n")
    subprocess.run(['chroot', str(ROOT), '/usr/bin/ucode', '-c', '-o', inside(temp / 'hostapd.ucb'), inside(wrapper)], check=True)
print('PASS: installed hostapd generator compiles and patch is idempotent')
