#!/usr/bin/env python3
"""Create descriptive public installer entries, shared by both bundle builders."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ACTIONS = {
    'install-to-tf-card': '--tf',
    'install-to-internal-storage': '--part',
    'reinstall-internal-system': '--reinstall-part',
    'resume-internal-install': '--resume-part',
    'switch-to-openwrt': '--boot-openwrt',
    'update-openwrt': '--update',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(package, source=HERE):
    package, source = Path(package).resolve(), Path(source).resolve()
    if package == source:
        raise ValueError('expected a separate package directory')
    package.mkdir(parents=True, exist_ok=True)
    internal = package / 'scripts/installer'; internal.mkdir(parents=True, exist_ok=True)
    for src, dest in (('flash.py', 'OpenWrt-Installer.py'), ('flash.cmd', 'start-installer.cmd'),
                      ('flash.sh', 'start-installer.sh')):
        shutil.copy2(source / src, package / dest)
    shutil.copy2(source / 'part-two-stage.py', internal / 'part-two-stage.py')
    exe = source / 'flash.exe'
    if exe.is_file():
        metadata = json.loads((source / 'flash-exe.json').read_text(encoding='utf-8'))
        if metadata != {'source_sha256': digest(source / 'flash.py'), 'binary_sha256': digest(exe)}:
            raise ValueError('Windows installer is stale; run python tools/build-flash-exe.py on Windows')
        shutil.copy2(exe, package / 'OpenWrt-Installer.exe')
        shutil.copy2(source / 'flash-exe.json', internal / 'flash-exe.json')
    for name, option in ACTIONS.items():
        cmd = '@echo off\r\ncd /d "%~dp0"\r\n'
        if name == 'resume-internal-install':
            cmd += ('set "TRANSACTION=%~1"\r\n'
                    'if not defined TRANSACTION set /p "TRANSACTION=Saved transaction.json path: "\r\n'
                    'if not defined TRANSACTION exit /b 1\r\n'
                    'call "%~dp0start-installer.cmd" --resume-part "%TRANSACTION%"\r\n')
            sh = ('#!/bin/sh\ncd "$(dirname "$0")" || exit 1\n'
                  'transaction=${1:-}\n'
                  'if [ -z "$transaction" ]; then printf "Saved transaction.json path: "; read -r transaction || exit 1; fi\n'
                  '[ -n "$transaction" ] || exit 1\n'
                  'exec sh ./start-installer.sh --resume-part "$transaction"\n')
        else:
            cmd += f'call "%~dp0start-installer.cmd" {option} %*\r\n'
            sh = ('#!/bin/sh\ncd "$(dirname "$0")" || exit 1\n'
                  f'exec sh ./start-installer.sh {option} "$@"\n')
        (package / (name + '.cmd')).write_bytes(cmd.encode('ascii'))
        target = package / (name + '.sh'); target.write_text(sh, encoding='utf-8', newline='\n'); target.chmod(0o755)
    (package / 'OpenWrt-Installer.py').chmod(0o755)
    (package / 'start-installer.sh').chmod(0o755)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    assemble(parser.parse_args().package)
