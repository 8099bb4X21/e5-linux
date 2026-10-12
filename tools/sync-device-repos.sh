#!/bin/sh
# Restore the exact repositories/commits recorded by the parent repository.
set -eu
TOP=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
git -C "$TOP" submodule sync --recursive
git -C "$TOP" submodule update --init --recursive
python3 "$TOP/tools/device-layout.py" check --system debian --model e5
for model in e5 t551m m8; do
    python3 "$TOP/tools/device-layout.py" check --system openwrt --model "$model"
done
