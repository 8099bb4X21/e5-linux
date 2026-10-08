#!/usr/bin/env python3
"""Read-only details cache. Never opens a tty or waits for AT in an HTTP request."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/tmp/run/e5-infoscreen')
CACHE = ROOT / 'details-radio.json'
QUERIES = {
    'lte': 'AT+SPLBAND=0', 'nr': 'AT+SPLBAND=3',
    'card': 'AT+SPACTCARD?', 'sa': 'AT+SP5GRAN?',
    'lte_cell': 'AT+SPFORCEFRQ=12,3', 'nr_cell': 'AT+SPFORCEFRQ=16,3',
}


def read_cache():
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def collect(channel, jobs):
    values = {}
    for key, command in jobs:
        try:
            # Persistent owners serialize each channel; nr2 stays available
            # for interactive commands and nr1 remains ModemManager's channel.
            result = subprocess.run(['/opt/e5/t551m-at', '--channel', str(channel),
                                     '-t', '2', command], capture_output=True, text=True, timeout=4)
            lines = [s.strip() for s in result.stdout.splitlines() if s.strip()]
            if result.returncode == 0 and lines and lines[-1] == 'OK':
                prefix = command[2:].split('=')[0].rstrip('?') + ':'
                values[key] = next((s for s in lines if s.startswith(prefix)), None)
            else:
                values[key] = None
        except (OSError, subprocess.TimeoutExpired):
            values[key] = None
    return values


def refresh():
    from concurrent.futures import ThreadPoolExecutor
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'details-radio.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if time.time() - read_cache().get('attempt', 0) < 30:
            return
        jobs = list(QUERIES.items())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(collect, 6+i, jobs[i::2]) for i in range(2)]
            values = {k: v for future in futures for k, v in future.result().items()}
        # Failed fields stay unknown, never become a false "not locked".
        data = {'attempt': time.time(), 'values': values,
                'error': any(v is None for v in values.values())}
        tmp = CACHE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data))
        os.replace(tmp, CACHE)


def main():
    if sys.argv[1:] == ['refresh']:
        refresh()
        return
    data = read_cache()
    if time.time() - data.get('attempt', 0) >= 30:
        subprocess.Popen([sys.executable, __file__, 'refresh'], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    data['pending'] = not data or time.time() - data.get('attempt', 0) >= 30
    print(json.dumps(data))


if __name__ == '__main__':
    main()
