#!/bin/bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m crawler.discover_wiki_assets --season ss13 --raw-root data/raw/manifests --output data/raw/assets/ss13/asset-manifest.json "$@"
