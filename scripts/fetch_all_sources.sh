#!/bin/bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/fetch_all_sources.sh [options]

Options:
  --system-id ID       Fetch one confirmed system
  --manifest PATH      Fetch one standalone source manifest
  --force              Re-download pages already in cache
  --max-workers N      Maximum concurrent requests (default: 4)
  --rate-limit SECONDS Minimum interval between request starts (default: 0.5)
  --quiet              Hide page-level progress
  --help               Show this help

With no --system-id or --manifest, all confirmed manifests are fetched.
EOF
}

system_id=""
manifest_path=""
force=0
max_workers="4"
rate_limit="0.5"
quiet=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --system-id)
      [ "$#" -ge 2 ] || { echo "Missing value for --system-id" >&2; exit 2; }
      system_id="$2"
      shift 2
      ;;
    --manifest)
      [ "$#" -ge 2 ] || { echo "Missing value for --manifest" >&2; exit 2; }
      manifest_path="$2"
      shift 2
      ;;
    --force)
      force=1
      shift
      ;;
    --max-workers)
      [ "$#" -ge 2 ] || { echo "Missing value for --max-workers" >&2; exit 2; }
      max_workers="$2"
      shift 2
      ;;
    --rate-limit)
      [ "$#" -ge 2 ] || { echo "Missing value for --rate-limit" >&2; exit 2; }
      rate_limit="$2"
      shift 2
      ;;
    --quiet)
      quiet=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -n "$system_id" ] && [ -n "$manifest_path" ]; then
  echo "--system-id and --manifest are mutually exclusive" >&2
  exit 2
fi

fetch_args=(--max-workers "$max_workers" --rate-limit "$rate_limit")

if [ -n "$manifest_path" ]; then
  fetch_args+=(--manifest "$manifest_path")
elif [ -n "$system_id" ]; then
  fetch_args+=(--system-manifest sources/system_manifest.json)
  fetch_args+=(--system-id "$system_id")
else
  fetch_args+=(--system-manifest sources/system_manifest.json)
  fetch_args+=(--all)
fi

if [ "$force" -eq 1 ]; then
  fetch_args+=(--force)
fi

if [ "$quiet" -eq 1 ]; then
  fetch_args+=(--quiet)
fi

python3 -m crawler.fetch_all_manifests "${fetch_args[@]}"
