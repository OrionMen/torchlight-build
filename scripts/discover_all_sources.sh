#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
force_args=()
season="ss13"

while [ "$#" -gt 0 ]; do
  case "$1" in
  --season)
    [ "$#" -ge 2 ] || { echo "Missing value for --season" >&2; exit 2; }
    season="$2"
    shift 2
    ;;
  --force)
    force_args=(--force); shift
    ;;
  --help|-h)
    cat <<'EOF'
Usage: ./scripts/discover_all_sources.sh [--season ID] [--force]

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
done

cd "$repo_root"
manifest_root="sources/seasons/$season"
system_manifest="$manifest_root/system_manifest.json"
if [ "$season" = "ss13" ] && [ ! -f "$system_manifest" ]; then
  system_manifest="sources/system_manifest.json"
fi
if [ ! -f "$system_manifest" ]; then
  echo "Missing $system_manifest" >&2
  echo "Run crawler.discover_systems and candidate verification first." >&2
  exit 1
fi

if [ "${#force_args[@]}" -gt 0 ]; then
  python3 -m crawler.discover_all_manifests \
    --system-manifest "$system_manifest" \
    --season "$season" \
    --all \
    --output-dir "$manifest_root" \
    "${force_args[@]}"
else
  python3 -m crawler.discover_all_manifests \
    --system-manifest "$system_manifest" \
    --season "$season" \
    --all \
    --output-dir "$manifest_root"
fi

echo "Manifest discovery complete"
echo "- system manifest: $system_manifest"
echo "- report directory: data/reports/local-wiki/$season/"
