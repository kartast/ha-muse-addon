#!/usr/bin/env bash
# Run the whole mock test suite: no hardware, no Home Assistant, no network
# beyond loopback. Usage: tests/run_tests.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/muse-gadget-bridge/sdk/src"

echo "== shell syntax: run.sh =="
bash -n muse-gadget-bridge/run.sh

echo "== python compiles: executor.py =="
python3 -m py_compile muse-gadget-bridge/sdk/src/musegadget/executor.py

echo "== unit tests =="
python3 -m unittest discover -s tests -v
