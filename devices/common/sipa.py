#!/usr/bin/env python3
"""Shared SIPA backpressure, completion and CP power-reference fixes."""
from pathlib import Path
import subprocess
import tempfile


PATCH = Path(__file__).with_name('sipa-data-path.patch')


def apply(kernel):
    kernel = Path(kernel).resolve()
    paths = [line[6:] for line in PATCH.read_text().splitlines() if line.startswith('+++ b/')]
    # Check the entire patch before writing any source. A different vendor
    # revision must fail explicitly rather than build a partial adaptation.
    with tempfile.TemporaryDirectory(prefix='e5-sipa-') as directory:
        stage = Path(directory)
        for name in paths:
            target = stage/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((kernel/name).read_bytes())
        args = ['git', 'apply', '--whitespace=nowarn']
        if subprocess.run(args + ['--reverse', '--check', str(PATCH)], cwd=stage,
                          capture_output=True).returncode == 0:
            return
        result = subprocess.run(args + ['--check', str(PATCH)], cwd=stage, capture_output=True, text=True)
        if result.returncode:
            raise ValueError('SIPA source differs from the supported revision: ' + result.stderr.strip())
        subprocess.run(args + [str(PATCH)], cwd=stage, check=True)
        for name in paths:
            (kernel/name).write_bytes((stage/name).read_bytes())


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    apply(parser.parse_args().kernel)
