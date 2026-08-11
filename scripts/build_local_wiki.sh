#!/bin/bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m crawler.build_local_wiki --season ss13 --system-manifest sources/system_manifest.json --raw-root data/raw/manifests --output local_wiki/ss13 "$@"
