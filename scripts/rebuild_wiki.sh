#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
season="ss13"
dry_run=0
max_rounds=8

usage() {
  cat <<'EOF'
Usage: ./scripts/rebuild_wiki.sh [--season ID] [--dry-run]

Rebuild the season-scoped Local Wiki data, assets, i18n, mirror, and validation.
Dry-run prints the resolved production commands without network access or writes.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --season)
      [ "$#" -ge 2 ] || { echo "Missing value for --season" >&2; exit 2; }
      season="$2"; shift 2 ;;
    --dry-run)
      dry_run=1; shift ;;
    --help|-h)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
command -v bash >/dev/null || { echo "bash is required" >&2; exit 1; }
cd "$repo_root"

source_root="sources/seasons/$season"
system_manifest="$source_root/system_manifest.json"
raw_root="data/raw/manifests/$season"
entity_root="data/generated/$season"
structured_root="data/generated/structured/$season"
asset_root="data/raw/assets/$season"
i18n_root="data/raw/i18n/$season"
report_root="data/reports/local-wiki/$season"
site_root="local_wiki/$season/site"
recovered_manifest="$source_root/recovered_internal_pages_manifest.json"
recovered_pending="$report_root/recovered-pending-manifest.json"
recovered_rejected="$report_root/recovered-rejected-pages.json"

run_cmd() {
  if [ "$dry_run" -eq 1 ]; then
    printf '  '; printf '%q ' "$@"; printf '\n'
  else
    "$@"
  fi
}

stage() { printf '\n[%s]\n' "$1"; }

printf 'Season: %s\n' "$season"
printf 'Paths:\n  %s\n  %s\n  %s\n  %s\n  %s\n  %s\n  %s\n' \
  "$source_root" "$raw_root" "$entity_root" "$structured_root" \
  "$asset_root" "$i18n_root" "$site_root"

stage "1 system-discovery"
run_cmd python3 -m crawler.discover_systems --season "$season" \
  --url https://tlidb.com/cn/ --output "$system_manifest" \
  --report "$report_root/system-discovery-report.json"

stage "2 candidate-verification-and-manifest-discovery"
run_cmd python3 -m crawler.verify_candidate_systems \
  --system-manifest "$system_manifest" --all --apply \
  --report "$report_root/candidate-verification-report.json" \
  --summary "$report_root/candidate-verification-summary.md"
run_cmd python3 -m crawler.discover_all_manifests --season "$season" \
  --system-manifest "$system_manifest" --all --output-dir "$source_root" \
  --report "$report_root/all-manifests-report.json"

stage "3 raw-fetch"
run_cmd python3 -m crawler.fetch_all_manifests --season "$season" \
  --system-manifest "$system_manifest" --all --output-root "$raw_root" \
  --report "$report_root/all-fetch-report.json"

stage "4 recovered-pages-convergence (max $max_rounds)"
if [ "$dry_run" -eq 1 ]; then
  run_cmd python3 -m crawler.discover_recovered_internal_pages \
    --system-manifest "$system_manifest" --raw-root "$raw_root" \
    --output "$recovered_manifest" --report "$report_root/recovered-pages-report.json" \
    --pending-output "$recovered_pending" \
    --rejected-state "$recovered_rejected" \
    --max-rounds "$max_rounds"
  run_cmd python3 -m crawler.fetch_all_manifests --season "$season" \
    --manifest "$recovered_pending" --output-root "$raw_root" \
    --report "$report_root/recovered-pending-fetch-report.json" \
    --recovered-rejected-output "$recovered_rejected"
  printf '  repeat until pending=0, unchanged, or %s rounds\n' "$max_rounds"
else
  previous_pending_hash=""
  pending=""
  for ((round=1; round<=max_rounds; round++)); do
    run_cmd python3 -m crawler.discover_recovered_internal_pages \
      --system-manifest "$system_manifest" --raw-root "$raw_root" \
      --output "$recovered_manifest" --report "$report_root/recovered-pages-report.json" \
      --pending-output "$recovered_pending" \
      --rejected-state "$recovered_rejected" \
      --max-rounds "$max_rounds"
    pending="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["entry_count"])' "$recovered_pending")"
    [ "$pending" = "0" ] && break
    pending_hash="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$recovered_pending")"
    [ "$pending_hash" = "$previous_pending_hash" ] && break
    previous_pending_hash="$pending_hash"
    run_cmd python3 -m crawler.fetch_all_manifests --season "$season" \
      --manifest "$recovered_pending" --output-root "$raw_root" \
      --report "$report_root/recovered-pending-fetch-report.json" \
      --recovered-rejected-output "$recovered_rejected"
  done
  [ "$pending" = "0" ] || { echo "Recovered convergence did not reach zero pending routes" >&2; exit 1; }
fi

stage "5 entity-v3"
run_cmd python3 -m crawler.generate_entity_index_v3 --season "$season" \
  --output "$entity_root/entity-index-v3.json" \
  --report "$report_root/entity-index-v3-generation-report.json"

stage "6 structured-modules"
run_cmd python3 -m crawler.structured.run_equipment_parser --season "$season"
run_cmd python3 -m crawler.structured.run_legendary_equipment_parser --season "$season"
run_cmd python3 -m crawler.structured.run_vorax_equipment_parser --season "$season"
run_cmd python3 -m crawler.structured.run_memory_structured_parser --season "$season"
run_cmd python3 -m crawler.structured.run_equipment_related_parser --season "$season"
run_cmd python3 -m crawler.structured.run_ethereal_prism_parser --season "$season"
run_cmd python3 -m crawler.structured.run_pact_fate_structured_parsers --season "$season"
run_cmd python3 -m crawler.structured.run_hero_trait_structured_parser --season "$season"
run_cmd python3 -m crawler.structured.run_remaining_talent_structured_parser --season "$season"
run_cmd python3 -m crawler.structured.run_skill_structured_parser --season "$season"

stage "7 structured-aggregate"
run_cmd python3 -m crawler.structured.aggregate_structured_search --season "$season"

stage "8 asset-convergence (max $max_rounds)"
if [ "$dry_run" -eq 1 ]; then
  run_cmd python3 -m crawler.discover_wiki_assets --season "$season" \
    --raw-root "$raw_root" --output "$asset_root/asset-manifest.json"
  run_cmd python3 -m crawler.fetch_wiki_assets --season "$season" \
    --manifest "$asset_root/asset-manifest.json" --output-root "$asset_root/files"
  printf '  repeat discover/fetch until no new CSS assets or %s rounds\n' "$max_rounds"
else
  for ((round=1; round<=max_rounds; round++)); do
    run_cmd python3 -m crawler.discover_wiki_assets --season "$season" \
      --raw-root "$raw_root" --output "$asset_root/asset-manifest.json"
    run_cmd python3 -m crawler.fetch_wiki_assets --season "$season" \
      --manifest "$asset_root/asset-manifest.json" --output-root "$asset_root/files"
    converged="$(python3 -c 'import json,sys; print(str(json.load(open(sys.argv[1]))["discovery_converged"]).lower())' "$asset_root/asset-discovery-report.json")"
    [ "$round" -gt 1 ] && [ "$converged" = "true" ] && break
  done
fi

stage "9 i18n"
run_cmd python3 -m crawler.discover_wiki_i18n --season "$season" \
  --raw-root "$raw_root" --asset-files "$asset_root/files" \
  --output "$report_root/i18n-discovery.json"
run_cmd python3 -m crawler.fetch_wiki_i18n --season "$season" \
  --discovery "$report_root/i18n-discovery.json" --output "$i18n_root"

stage "10 full-mirror"
run_cmd python3 -m crawler.build_full_wiki_mirror --season "$season" --force \
  --raw-root "$raw_root" --system-manifest "$system_manifest" \
  --supplemental-manifest "$recovered_manifest" \
  --entity-index "$entity_root/entity-index-v3.json" \
  --structured-search-index "$structured_root/structured-search-index.json" \
  --asset-manifest "$asset_root/asset-manifest.json" --asset-root "$asset_root/files" \
  --i18n-root "$i18n_root/files" --output "$site_root"

stage "11 validation"
run_cmd python3 -m crawler.validate_season_rebuild --season "$season"
