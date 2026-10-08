#!/usr/bin/python3
"""Serialize backlight/touch transitions and reconcile out-of-band changes.

Input-core inhibition releases held contacts and drops all subsequent events.
Never unbind/reset/reflash the touch controller. Physical keys stay available.
"""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time

SYS = Path('/sys')
LOCK = Path('/run/t551m-screen-power.lock')


def touch_allowed():
    result = subprocess.run(['uci', '-q', 'get', 'e5-infoscreen.main.touch'],
                            capture_output=True, text=True, timeout=3)
    return result.stdout.strip() != '0'


def devices():
    backlights = list((SYS / 'class/backlight').glob('*/brightness'))
    touches = [p / 'inhibited' for p in (SYS / 'class/input').glob('input*')
               if (p / 'name').read_text().strip() == 'tlsc6x_touch']
    if not backlights or not touches:
        raise RuntimeError('T551M backlight or touch device missing')
    return backlights, touches


def inhibit(touches, disabled):
    value = '1' if disabled else '0'
    for path in touches:
        if path.read_text().strip() != value:
            path.write_text(value + '\n')
        if path.read_text().strip() != value:
            raise RuntimeError('Touch inhibition did not take effect')


def reconcile(level=None, allowed=None):
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        backlights, touches = devices()
        if allowed is None:
            allowed = touch_allowed()
        if level is not None:
            level = max(0, min(255, int(level)))
            # Disable before darkening; restore before lighting. JS keeps the
            # lock and its wake guard engaged throughout either transition.
            inhibit(touches, not (level > 0 and allowed))
            for path in backlights:
                path.write_text(str(level) + '\n')
        on = any(int(p.read_text()) > 0 for p in backlights)
        inhibit(touches, not (on and allowed))


def watch():
    allowed, refresh, last_error, previous_config = True, 0, None, None
    while True:
        try:
            current_config = Path('/etc/config/e5-infoscreen').stat().st_mtime_ns
            if time.monotonic() >= refresh or current_config != previous_config:
                allowed = touch_allowed()
                refresh = time.monotonic() + 1
                previous_config = current_config
            reconcile(allowed=allowed)
            last_error = None
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            if str(error) != last_error:
                print('t551m-screen-power: ' + str(error), flush=True)
                last_error = str(error)
        time.sleep(.1)


if __name__ == '__main__':
    os.umask(0o077)
    if len(sys.argv) == 2 and sys.argv[1] == 'watch':
        watch()
    elif len(sys.argv) == 2 and sys.argv[1] == 'sync':
        reconcile()
    elif len(sys.argv) == 3 and sys.argv[1] == 'set':
        reconcile(int(sys.argv[2]))
    else:
        raise SystemExit('usage: t551m-screen-power watch|sync|set LEVEL')
