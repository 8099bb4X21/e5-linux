#!/usr/bin/env python3
"""Apply T551M networking startup settings to an existing OpenWrt root."""
import argparse
from pathlib import Path
import re


def patch_root(root, profile='t551m'):
    if profile not in ('t551m', 'e5'):
        raise ValueError('Unknown device profile: ' + profile)
    config = root / 'etc/config/unisoc_modem'
    if config.exists() and profile == 't551m':
        text = config.read_text()
        if 'option lte_supported_bands ' not in text:
            anchor = "config core 'main'\n"
            if text.count(anchor) != 1:
                raise ValueError('Unexpected modem dashboard configuration')
            # This firmware drops B38 from SPLBAND readback; the imported
            # dashboard's larger fallback list is not a capability query.
            config.write_text(text.replace(anchor, anchor + "\toption lte_supported_bands '1,3,5,8,34,39,40,41'\n"))

    wrapper = root / 'usr/sbin/ModemManager-wrapper'
    if wrapper.exists():
        text = wrapper.read_text()
        if '# unisoc-pre-dial-replay' not in text:
            anchor = '\t/usr/sbin/ModemManager "$@" 1>/dev/null 2>/dev/null &'
            if text.count(anchor) != 1:
                raise ValueError('Unexpected ModemManager startup wrapper')
            text = text.replace(anchor, '''\t# unisoc-pre-dial-replay: finish saved AT settings before MM can enable/dial.
\tif [ -x /usr/libexec/unisoc-modem/boot-replay ]; then
\t\t/usr/libexec/unisoc-modem/boot-replay early ||
\t\t\tlogger -t unisoc-modem "pre-dial replay failed; continuing without a late radio cycle"
\tfi

''' + anchor)
            wrapper.write_text(text)

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
        if 'preserve AT-selected network mode' not in text:
            old = '\tif [ -z "${allowedmode}" ]; then\n\t\tmodemmanager_set_allowed_mode "$device" "$interface" "any"'
            if text.count(old) != 1:
                raise ValueError('Unexpected ModemManager default mode configuration')
            text = text.replace(old, '''\tif [ -z "${allowedmode}" ]; then
\t\t# preserve AT-selected network mode; Unisoc's MM mode setter is unsupported.
\t\t# Boot replay already applied the user's preference before radio activation.
\t\techo "Keeping current network mode (no WAN override configured)"''')
            proto.write_text(text)
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
    parser.add_argument('--profile', choices=('t551m', 'e5'), default='t551m')
    args = parser.parse_args()
    patch_root(args.root, args.profile)
