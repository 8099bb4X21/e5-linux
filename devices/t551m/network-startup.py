#!/usr/bin/env python3
"""Apply T551M networking startup settings to an existing OpenWrt root."""
import argparse
from pathlib import Path
import re


def patch_root(root):
    loader = root / 'etc/init.d/e5-sipc-wwan'
    if loader.exists():
        text = loader.read_text()
        if 'tx_gap_ms=100' not in text:
            old = 'insmod $M/sipc_wwan.ko card=$C'
            if text.count(old) != 1:
                raise ValueError('Unexpected SIPC loader')
            text = text.replace(old, old + ' tx_gap_ms=100')
            text = text.replace('insmod $M/sipc_wwan.ko;', 'insmod $M/sipc_wwan.ko tx_gap_ms=100;')
            loader.write_text(text)

    proto = root / 'lib/netifd/proto/modemmanager.sh'
    if proto.exists():
        text = proto.read_text()
        if 'T551M: preserve initial EPS' not in text:
            old = '\t\tcase "$init_epsbearer" in\n'
            if text.count(old) != 1:
                raise ValueError('Unexpected ModemManager initial EPS configuration')
            text = text.replace(old, old + '''\t\t\t"keep")
\t\t\t\t# T551M: preserve initial EPS; simple-connect still sets the APN.
\t\t\t\t# Rewriting it after registration forces CFUN=4/1 and a second search.
\t\t\t\techo "Keeping initial EPS bearer; applying connection APN at dial"
\t\t\t\t;;
''')
            proto.write_text(text)

    luci = root / 'www/luci-static/resources/protocol/modemmanager.js'
    if luci.exists():
        text = luci.read_text()
        if "o.value('keep'" not in text:
            # Works with the upstream readable source and APK's minified source.
            pattern = r"(o\.value\(\s*'custom'\s*,\s*'custom'\s*\);)"
            text, count = re.subn(pattern,
                r"\1o.value('keep', _('Keep existing initial EPS bearer'));", text)
            if count != 1:
                raise ValueError('Unexpected ModemManager LuCI options')
            luci.write_text(text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    patch_root(parser.parse_args().root)
