#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
extra_args=()

for argument in "$@"; do
  case "$argument" in
    --apply|--force|--strict|--debug)
      extra_args+=("$argument")
      ;;
    --help|-h)
      cat <<'EOF'
Usage: ./scripts/verify_candidate_systems.sh [--apply] [--force] [--strict] [--debug]

By default, verify every candidate system and generate reports without changing
sources/system_manifest.json. --apply applies trustworthy classifications after
creating a backup. No detail pages are requested.
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $argument" >&2
      echo "Use --help for usage." >&2
      exit 2
      ;;
  esac
done

cd "$repo_root"
if [ "${#extra_args[@]}" -gt 0 ]; then
  python3 -m crawler.verify_candidate_systems \
    --system-manifest sources/system_manifest.json \
    --all \
    --report data/reports/system-discovery/candidate-verification-report.json \
    --summary data/reports/system-discovery/candidate-verification-summary.md \
    "${extra_args[@]}"
else
  python3 -m crawler.verify_candidate_systems \
    --system-manifest sources/system_manifest.json \
    --all \
    --report data/reports/system-discovery/candidate-verification-report.json \
    --summary data/reports/system-discovery/candidate-verification-summary.md
fi
