#!/usr/bin/env python3
"""Validate device repositories and compose distro overlays in dependency order."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

TOP = Path(__file__).resolve().parents[1]
LAYOUT = TOP / 'device/manifest.json'


def repositories(system, model):
    data = json.loads(LAYOUT.read_text())
    try:
        names = data['profiles'][system][model]
    except KeyError:
        raise ValueError('Unsupported system/device: ' + system + '/' + model)
    paths = [(TOP / 'device' / name).resolve() for name in names]
    for name, path in zip(names, paths):
        if not (path / 'profile.json').is_file():
            raise ValueError('Missing device repository: ' + str(path) + '; run tools/sync-device-repos.sh')
        metadata = json.loads((path / 'profile.json').read_text())
        system_name, _, model_name = name.partition('_device_')
        if metadata.get('schema') != 1 or metadata.get('system') != system_name or metadata.get('model') != model_name:
            raise ValueError('Device repository identity mismatch: ' + name)
    return paths


def compose(system, model, output, private_overlay=None):
    sources = repositories(system, model)
    output = Path(output).resolve()
    if output == Path('/') or output == TOP.resolve() or any(output == p or output in p.parents or p in output.parents for p in sources):
        raise ValueError('Output must be separate from source repositories')
    marker = '.device-overlay.json'
    if output.exists() and any(output.iterdir()) and not (output / marker).is_file():
        raise ValueError('Refusing to replace a directory that is not a generated overlay: ' + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.device-overlay-', dir=output.parent) as temp:
        target = Path(temp) / 'overlay'
        target.mkdir()
        overlays = [source / 'overlay' for source in sources]
        if private_overlay:
            private_overlay = Path(private_overlay).resolve()
            if not private_overlay.is_dir():
                raise ValueError('Private overlay is missing: ' + str(private_overlay))
            if output == private_overlay or output in private_overlay.parents or private_overlay in output.parents:
                raise ValueError('Output must be separate from the private overlay')
            overlays.append(private_overlay)
        for overlay in overlays:
            if not overlay.is_dir():
                continue
            for entry in sorted(overlay.rglob('*')):
                relative = entry.relative_to(overlay)
                if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
                    continue
                dest = target / relative
                if entry.is_dir() and not entry.is_symlink():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_symlink() or dest.is_file():
                    dest.unlink()
                if entry.is_symlink():
                    dest.symlink_to(entry.readlink())
                else:
                    shutil.copy2(entry, dest)
        (target / marker).write_text(json.dumps({'system': system, 'model': model,
            'repositories': [p.name for p in sources]}, indent=2) + '\n')
        if output.exists():
            shutil.rmtree(output)
        target.rename(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'overlay', 'list'))
    parser.add_argument('--system', default='openwrt')
    parser.add_argument('--model', default='e5')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--private-overlay', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'list':
            data = json.loads(LAYOUT.read_text())
            for system, models in data['profiles'].items():
                for model in models:
                    print(system + '/' + model)
        elif args.command == 'overlay':
            print(compose(args.system, args.model, args.out or TOP / 'work/overlays' / (args.system + '-' + args.model), args.private_overlay))
        else:
            for repo in repositories(args.system, args.model):
                print(repo.relative_to(TOP))
    except ValueError as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
