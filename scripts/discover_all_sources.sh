#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
force_args=()

case "${1:-}" in
  "")
    ;;
  --force)
    force_args=(--force)
    ;;
  --help|-h)
    cat <<'EOF'
Usage: ./scripts/discover_all_sources.sh [--force]

Generate manifests for confirmed systems in the existing reviewed system manifest.
Run crawler.discover_systems separately when a fresh system discovery is required.
Existing child manifests are skipped unless --force is supplied.
This script does not download detail page bodies.
EOF
    exit 0
    ;;
  *)
    echo "Unknown argument: $1" >&2
    echo "Use --help for usage." >&2
    exit 2
    ;;
esac

cd "$repo_root"
if [ ! -f sources/system_manifest.json ]; then
  echo "Missing sources/system_manifest.json" >&2
  echo "Run crawler.discover_systems and candidate verification first." >&2
  exit 1
fi

if [ "${#force_args[@]}" -gt 0 ]; then
  python3 -m crawler.discover_all_manifests \
    --system-manifest sources/system_manifest.json \
    --all \
    --output-dir sources \
    "${force_args[@]}"
else
  python3 -m crawler.discover_all_manifests \
    --system-manifest sources/system_manifest.json \
    --all \
    --output-dir sources
fi

echo "Manifest discovery complete"
echo "- system manifest: sources/system_manifest.json"
echo "- report directory: data/reports/system-discovery/"
