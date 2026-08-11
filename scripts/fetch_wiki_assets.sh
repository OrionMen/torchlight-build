#!/bin/bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m crawler.fetch_wiki_assets --manifest data/raw/assets/ss13/asset-manifest.json --output-root data/raw/assets/ss13/files "$@"
