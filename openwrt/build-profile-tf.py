#!/usr/bin/env python3
"""Assemble a clean TF installer from tested package binaries and matching kernels.

Linux/WSL, root required. Inputs are explicit; no connected device is accessed.
The clean base must be firmware/credential-free. This is incremental assembly,
not a full OpenWrt SDK rebuild. Each output records source and input hashes.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import time
import zipfile

TOP = Path(__file__).resolve().parents[1]
MODELS = {'e5': ['E5'], 't551m': ['T551M'], 'm8': ['VIPME M8']}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def run(*args, **kwargs):
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', choices=MODELS, required=True)
    for name in ('base', 'defaults', 'kernel', 'stock-boot', 'misc-head', 'busybox', 'work', 'output', 'block-apk'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--apk-image', default='mu300-openwrt-base:25.12.5')
    p.add_argument('--cc', default='aarch64-linux-gnu-gcc')
    a = p.parse_args()
    if os.geteuid() != 0 or a.work.exists():
        p.error('Run as root with a new work directory')
    expected_id = runpy.run_path(str(TOP / 'tools/ci-release.py'))['block_build_id']()
    if Path(str(a.block_apk) + '.build-id').read_text().strip() != expected_id:
        raise ValueError('block-mount is not built from the current probe guard')
    if Path(str(a.block_apk) + '.sha256').read_text().split()[0] != digest(a.block_apk):
        raise ValueError('block-mount APK checksum mismatch')
    a.work.mkdir(parents=True)
    root = a.work / 'root'
    release = runpy.run_path(str(TOP / 'upstream/check-container-support.py'))['check'](a.kernel)
    if f'-{a.profile}-' not in release:
        raise ValueError('Wrong kernel profile: ' + release)
    if b'e5.openwrt=' in (a.kernel / 'Image').read_bytes():
        raise ValueError('Trial kernel forces userdata boot; rebuild without e5.openwrt= for TF')
    prepare = runpy.run_path(str(TOP / 'devices/m8/prepare-root.py'))['prepare']
    prepare(a.base, root, a.defaults, profile=a.profile)
    helpers = {}
    for n, target in (('logdw', 'opt/e5/bin/logdw'), ('e5-vibrate', 'usr/bin/e5-vibrate'),
                      ('e5-ctl-raw', 'opt/e5/e5-ctl-raw'), ('e5-modemd', 'usr/sbin/e5-modemd'),
                      ('e5-sim-probe', 'usr/libexec/e5-sim-probe')):
        src = TOP / ('openwrt/src/' + n + '.c')
        run(a.cc, '-static', '-Os', '-s', '-Wall', '-o', root / target, src)
        helpers[target] = {'source_sha256': digest(src), 'binary_sha256': digest(root / target)}
    # Keep the pristine upstream first-boot hooks present in the clean base.
    # The common stager refreshes their repository-owned replacements.
    for kind in ('storage', 'network'):
        target = root / ('etc/modules.d/55-usb-host-' + kind)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((TOP / f'devices/t551m/usb-host-{kind}.modules').read_bytes().replace(b'\r\n', b'\n'))
        # Avoid loading the same list twice under old aliases.
        for old in (f'etc/modules.d/usb-host-{kind}', f'etc/modules.d/56-usb-host-{kind}'):
            (root / old).unlink(missing_ok=True)
    runpy.run_path(str(TOP / 'upstream/stage-root-modules.py'))['stage'](a.kernel, root)
    # apk handles the package database/dependencies; never copy just /sbin/block.
    run('docker', 'run', '--rm', '--platform', 'linux/arm64',
        '-v', f'{root}:/target', '-v', f'{a.block_apk.resolve()}:/input/block.apk:ro',
        '--entrypoint', '/bin/sh', a.apk_image, '-ec',
        'apk --root /target --no-scripts --no-network add --allow-untrusted /input/block.apk')
    # The SMS forward signs DingTalk webhooks with the openssl CLI and sends SMTP
    # through msmtp; the clean base carries the backend files without the packages.
    # (downloads.openwrt.org interrupts mid-index often enough that the same
    #  retry loop mu300-linux's builder uses belongs here too)
    run('docker', 'run', '--rm', '--platform', 'linux/arm64',
        '-v', f'{root}:/target', '--entrypoint', '/bin/sh', a.apk_image, '-ec',
        'ok=; for n in 1 2 3; do apk --root /target --no-scripts add openssl-util msmtp && '
        '{ ok=1; break; }; echo "apk download interrupted (attempt $n), retrying" >&2; sleep 3; done; '
        '[ -n "$ok" ]')
    forward = {}
    for pkg in ('openssl-util', 'msmtp'):
        match = re.search(rf'^P:{pkg}$\n^V:(\S+)$', (root / 'lib/apk/db/installed').read_text(), re.M)
        if not match:
            raise ValueError(f'the TF image has no {pkg}: the SMS forward needs it')
        forward[pkg] = match.group(1)
    (root / 'etc/e5/block-mount.build-id').write_bytes(Path(str(a.block_apk) + '.build-id').read_bytes())
    # Do not execute target init scripts on the build host.
    fstab = (root / 'etc/init.d/fstab').read_text()
    for action, prefix in (('START', 'S'), ('STOP', 'K')):
        match = re.search(r'^' + action + r'=(\d+)$', fstab, re.M)
        if match:
            path = root / 'etc/rc.d' / (prefix + match[1].zfill(2) + 'fstab')
            if not path.is_symlink():
                path.symlink_to('../init.d/fstab')
    # Avoid host umasks/CRLF or stale Python bytecode in target scripts.
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                os.lchown(path, 0, 0)
                continue
            data = path.read_bytes()
            if data.startswith(b'#!'):
                path.write_bytes(data.replace(b'\r\n', b'\n'))
                path.chmod(0o755)
            os.chown(path, 0, 0)
        for name in dirs:
            os.lchown(Path(directory) / name, 0, 0)
    # apk may create a temporary cache, which has no place in the image.
    for child in (root / 'tmp').iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    epoch = int(time.time())
    rev = subprocess.check_output(['git', '-c', 'safe.directory=' + str(TOP), '-C', str(TOP), 'rev-parse', 'HEAD'], text=True).strip()
    name = f'{a.profile}-openwrt-25.12.5-tf-' + time.strftime('%Y%m%d-%H%M%S')
    package = a.work / name
    files = package / 'files'
    files.mkdir(parents=True)
    init = a.work / 'init'
    init.write_bytes((TOP / 'boot/init').read_bytes().replace(b'\r\n', b'\n'))
    run('python3', TOP / 'boot/build-boot-image.py', '--stock-boot', a.stock_boot,
        '--misc-head', a.misc_head, '--kernel', a.kernel / 'Image.lk',
        '--modules', a.kernel / 'modules', '--module-order', a.kernel / 'module-order.txt',
        '--busybox', a.busybox, '--init', init, '--cmdline', '', '--out', files / 'boot.img')
    boot = json.loads((files / 'boot.json').read_text())
    assert boot['overlay_files'] == 0 and boot['cmdline'] == 'e5.part_v=2'
    (files / 'boot.misc-slot-b-trial.bin').rename(files / 'boot-misc-slot-b.bin')
    sources = {}
    # Includes uncommitted source fixes, so HEAD alone cannot misidentify a build.
    names = subprocess.check_output(['git', '-c', 'safe.directory=' + str(TOP), '-C', str(TOP),
                                     'ls-files', '--cached', '--others', '--exclude-standard', '-z']).decode().split('\0')
    for n in sorted(set(names)):
        if n.startswith(('boot/', 'devices/', 'openwrt/', 'rootfs/overlay/', 'tools/', 'upstream/')) and (TOP / n).is_file():
            sources[n] = digest(TOP / n)
    info = {'name': name, 'profile': a.profile, 'source_commit': rev,
            'build_epoch': epoch, 'kernel_release': release, 'openwrt': '25.12.5',
            'build_type': 'incremental assembly; tested package binaries, current sources, rebuilt initramfs',
            'docker_preinstalled': False, 'root_image_bytes': 2147483648,
            'boot_sha256': boot['sha256'], 'block_mount_sha256': digest(a.block_apk),
            'forward_packages': forward,
            'hardware_validation': 'TF installer and final image not flashed; offline checks only',
            'kernel_manifest': json.loads((a.kernel / 'container-support.json').read_text()),
            'compiled_helpers': helpers,
            'modemmanager_sha256': digest(root / 'usr/sbin/ModemManager'),
            'sources': sources}
    for dest in (root / 'etc/e5/build.json', package / 'BUILD.json'):
        dest.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n')
    (root / 'etc/e5/image-version').write_text(name + '\n')
    (root / 'etc/e5/build-time').write_text(str(epoch) + '\n')
    feature = root / 'etc/e5/feature-port.json'
    if feature.exists():
        data = json.loads(feature.read_text())
        data.update(status='tf-package', hardware_validation=info['hardware_validation'])
        feature.write_text(json.dumps(data, indent=2) + '\n')
    audit(root, a.profile, release)
    image = a.work / 'openwrt.ext4'
    run('mke2fs', '-q', '-t', 'ext4', '-L', 'e5-openwrt', '-m', '1', '-d', root, image, '2048M')
    run('e2fsck', '-fn', image)
    with (files / 'openwrt.ext4.gz').open('wb') as out:
        run('gzip', '-1', '-c', image, stdout=out)
    runpy.run_path(str(TOP / 'openwrt/prepare-ext4-tools.py'))['build'](root, files / 'ext4-tools.tar')
    for n in ('flash.py', 'flash.cmd', 'flash.sh', 'install-part.cmd', 'install-part.sh',
              'reinstall.cmd', 'reinstall.sh', 'part-two-stage.py', 'README.md', 'README.zh-CN.md'):
        shutil.copy2(TOP / 'openwrt/bundle' / n, package / n)
    # A Windows build of the flasher (work/build-flash-exe.cmd) ships with the
    # package when it is there: users without Python run flash.exe instead.
    exe = TOP / 'openwrt/bundle/flash.exe'
    if exe.is_file():
        shutil.copy2(exe, package / 'flash.exe')
    for n in ('device-install-image.sh', 'device-flash-boot.sh', 'device-install-part.sh'):
        shutil.copy2(TOP / 'openwrt' / n, files / n)
    (files / 'part-write.sh').write_bytes((TOP / 'openwrt/bundle/part-write.sh').read_bytes().replace(b'\r\n', b'\n'))
    for src in ('openwrt/bundle/collect-device-files.sh', 'openwrt/overlay/usr/libexec/e5-gpt', 'tools/android-bootchain.sh'):
        target = files / Path(src).name
        target.write_bytes((TOP / src).read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(0o755)
    tools = package / 'scripts/tools'
    tools.mkdir(parents=True)
    for n in ('e5-telnet.py', 'sprd-bt-config.py'):
        shutil.copy2(TOP / 'tools' / n, tools / n)
    shutil.copytree(TOP / 'tools/vbc-profile', tools / 'vbc-profile', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(TOP / 'LICENSE', package / 'LICENSE')
    (files / 'device-profile.json').write_text(json.dumps({'profile': a.profile, 'android_models': MODELS[a.profile]}) + '\n')
    (files / 'VERSION').write_text(name + ' (' + release + ')\n')
    (package / 'START-HERE.zh-CN.md').write_text(f'''# {MODELS[a.profile][0]} TF 卡安装包

仅用于 {MODELS[a.profile][0]}，不要跨机型刷入。解压后，在电脑运行 flash.cmd（Windows）或 bash flash.sh。
需要 Python 3.8+、ADB、已解锁且已 root 的 Android A 槽、Magisk BusyBox。
首次安装会重新分区并清空整张 TF 卡：至少 4 GB，建议 8 GB 以上。
系统分区约 2 GiB，其余容量留作后续扩展/升级；不是使用已有分区全容量的安装方式。
先检查包和启动链、提取本机固件，再释放卡、备份同步有差异的 B 槽启动链、写系统并只读校验，最后写 boot_b 和切槽。
安装器不会自动重启；成功后自行重启进入 OpenWrt。Android A 的启动分区不覆盖。
此包不包含私有固件、NV、用户配置、主机密钥；安装时从目标机提取固件。
首次登录 192.168.9.1，账号 root，密码 root；进入后修改密码。
保留 Docker/KVM 内核支持，不预装 Docker。
已完成离线文件系统、模块/内核匹配、包校验；这份完整 TF 包尚未实机安装测试。
详细步骤见 README.zh-CN.md。
''', encoding='utf-8')
    checks = {p.relative_to(package).as_posix(): digest(p) for p in sorted(package.rglob('*')) if p.is_file()}
    (package / 'SHA256SUMS').write_text(''.join(v + '  ' + k + '\n' for k, v in checks.items()))
    spec = importlib.util.spec_from_file_location('packaged_flash', package / 'flash.py')
    flash = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flash)
    flash.check_package()
    assert flash.gz_usize(str(files / 'openwrt.ext4.gz')) == 2147483648
    a.output.mkdir(parents=True, exist_ok=True)
    archive = a.work / (name + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for src in sorted(package.rglob('*')):
            if src.is_file() and '__pycache__' not in src.parts:
                z.write(src, name + '/' + src.relative_to(package).as_posix(),
                        compress_type=zipfile.ZIP_STORED if src.suffix == '.gz' else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for n, want in checks.items():
            with z.open(name + '/' + n) as stream:
                h = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    h.update(chunk)
            assert h.hexdigest() == want, n
    target = a.output / archive.name
    shutil.copyfile(archive, target)
    assert digest(target) == digest(archive)
    (a.output / (archive.name + '.sha256')).write_text(digest(target) + '  ' + target.name + '\n')
    shutil.copyfile(package / 'BUILD.json', a.output / (name + '.json'))
    print('RELEASE:', target, target.stat().st_size, flush=True)


def audit(root, profile, release):
    assert (root / 'etc/e5/device-profile').read_text().strip() == profile
    assert [p.name for p in (root / 'lib/modules').iterdir()] == [release]
    for directory in ('opt/e5/android', 'etc/dropbear', 'etc/ssh', 'root', 'tmp'):
        assert not any((root / directory).iterdir()), directory
    for name in ('etc/e5/install.conf', 'etc/e5/sd-root', 'etc/e5/contacts.json', 'etc/e5-sms',
                 'etc/unisoc-modem', 'etc/uhttpd.key', 'etc/uhttpd.crt', 'usr/bin/dockerd',
                 'usr/bin/docker', 'usr/bin/containerd', 'usr/bin/runc'):
        assert not (root / name).exists(), name
    assert all(p.name in ('regulatory.db', 'regulatory.db.p7s', 'rtl_nic') for p in (root / 'lib/firmware').iterdir())
    assert (root / 'etc/shadow').read_text().startswith('root::')
    assert (root / 'etc/machine-id').read_text() == ''
    for name in ('sbin/block', 'lib/libblkid-tiny.so', 'etc/init.d/fstab',
                 'usr/sbin/ModemManager', 'usr/libexec/e5-infoscreen/session',
                 'usr/bin/openssl', 'usr/bin/msmtp'):
        assert (root / name).stat().st_size, name
    modem = (root / 'etc/config/unisoc_modem').read_text()
    assert ('auto_work_mode' in modem) == (profile == 't551m')
    if profile == 'm8':
        assert (root / 'etc/e5/receiver-volume-ceiling').read_text().strip() == '5'
    print('Clean root audit passed:', profile, flush=True)


if __name__ == '__main__':
    main()
