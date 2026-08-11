#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_OUTPUT="$REPO_ROOT/Torchlight-ai-source.zip"
OUTPUT=""
SYSTEM_ID=""

usage() {
  cat <<'EOF'
Usage: export_ai_source.sh [--system <system_id>] [--output <path>] [--help]

Without --system, build the existing Core Bundle without raw HTML.
With --system, build a focused bundle including that system's raw HTML.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --system)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "Error: --system requires a system_id." >&2
        exit 2
      fi
      SYSTEM_ID="$2"
      shift 2
      ;;
    --output)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "Error: --output requires a path." >&2
        exit 2
      fi
      OUTPUT="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$SYSTEM_ID" ]]; then
  case "$SYSTEM_ID" in
    *[!A-Za-z0-9_-]*)
      echo "Error: invalid system_id: $SYSTEM_ID" >&2
      exit 2
      ;;
  esac
fi

if [[ -z "$OUTPUT" ]]; then
  if [[ -n "$SYSTEM_ID" ]]; then
    OUTPUT="$REPO_ROOT/Torchlight-system-${SYSTEM_ID}.zip"
  else
    OUTPUT="$DEFAULT_OUTPUT"
  fi
fi

SYSTEM_STATUS=""
SYSTEM_INDEX_URL=""
SYSTEM_MANIFEST_REL=""
if [[ -n "$SYSTEM_ID" ]]; then
  SYSTEM_RECORD="$(python3 - "$REPO_ROOT/sources/system_manifest.json" "$SYSTEM_ID" <<'PY'
import json
import sys

path, requested = sys.argv[1:]
with open(path, encoding="utf-8") as source:
    systems = json.load(source).get("systems", [])
matches = [item for item in systems if item.get("system_id") == requested]
if len(matches) != 1:
    print(
        f"Error: unknown system_id: {requested}. See sources/system_manifest.json.",
        file=sys.stderr,
    )
    raise SystemExit(2)
item = matches[0]
print(item.get("discovery_status") or item.get("classification_status") or "unknown")
print(item.get("index_url") or "unknown")
print(item.get("manifest_path") or f"sources/{requested}_manifest.json")
PY
)" || exit $?
  SYSTEM_STATUS="$(printf '%s\n' "$SYSTEM_RECORD" | sed -n '1p')"
  SYSTEM_INDEX_URL="$(printf '%s\n' "$SYSTEM_RECORD" | sed -n '2p')"
  SYSTEM_MANIFEST_REL="$(printf '%s\n' "$SYSTEM_RECORD" | sed -n '3p')"
  if [[ ! -f "$REPO_ROOT/$SYSTEM_MANIFEST_REL" && ! -d "$REPO_ROOT/data/raw/manifests/$SYSTEM_ID" ]]; then
    echo "Error: no exportable data directory or manifest for system_id: $SYSTEM_ID" >&2
    exit 2
  fi
fi

if [[ "$OUTPUT" != /* ]]; then
  OUTPUT="$PWD/$OUTPUT"
fi

OUTPUT_DIR="$(dirname "$OUTPUT")"
mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT"

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/torchlight-ai-source.XXXXXX")"
STAGING="$TEMP_ROOT/staging"
SECRET_LIST="$TEMP_ROOT/secret-paths.txt"
mkdir -p "$STAGING"
trap 'rm -rf "$TEMP_ROOT"' EXIT INT TERM

copy_path() {
  local relative="$1"
  local source="$REPO_ROOT/$relative"
  local destination="$STAGING/$relative"
  if [[ ! -e "$source" ]]; then
    return
  fi
  mkdir -p "$(dirname "$destination")"
  cp -R "$source" "$destination"
}

ROOT_FILES=(
  README.md
  PROJECT_STATE.md
  PROJECT_MEMORY.md
  DATA_MODEL.md
  DECISIONS.md
  .gitignore
)

PROJECT_DIRS=(
  architecture
  decisions
  docs
  knowledge
  research
  schemas
  spec
  tasks
  app
  crawler
  engine
  scripts
  tests
  sources
)

DATA_DIRS=(
  data/structured
  data/parsed
  data/modeled
  data/review
  data/extracted/tooltips
  data/reports
)

if [[ -z "$SYSTEM_ID" ]]; then
  for path in "${ROOT_FILES[@]}"; do
    copy_path "$path"
  done
  for path in "${PROJECT_DIRS[@]}"; do
    copy_path "$path"
  done
  for path in "${DATA_DIRS[@]}"; do
    copy_path "$path"
  done

  if [[ -d "$REPO_ROOT/data/raw/manifests" ]]; then
    for manifest_dir in "$REPO_ROOT"/data/raw/manifests/*; do
      [[ -d "$manifest_dir" ]] || continue
      manifest_name="$(basename "$manifest_dir")"
      copy_path "data/raw/manifests/$manifest_name/meta"
      copy_path "data/raw/manifests/$manifest_name/reports"
    done
  fi
else
  copy_path "README.md"
  copy_path "PROJECT_STATE.md"
  copy_path "$SYSTEM_MANIFEST_REL"
  copy_path "data/raw/manifests/$SYSTEM_ID"

  for base in data/structured data/parsed data/modeled; do
    copy_path "$base/$SYSTEM_ID"
    copy_path "$base/${SYSTEM_ID}s"
  done
  copy_path "knowledge/$SYSTEM_ID"
  copy_path "research/$SYSTEM_ID"

  for content_root in "$REPO_ROOT"/knowledge/* "$REPO_ROOT"/research/*; do
    [[ -d "$content_root/$SYSTEM_ID" ]] || continue
    relative_root="${content_root#"$REPO_ROOT/"}"
    copy_path "$relative_root/$SYSTEM_ID"
  done

  if [[ -d "$REPO_ROOT/data/extracted/tooltips" ]]; then
    for tooltip_root in "$REPO_ROOT"/data/extracted/tooltips/*; do
      [[ -d "$tooltip_root/$SYSTEM_ID" ]] || continue
      relative_root="${tooltip_root#"$REPO_ROOT/"}"
      copy_path "$relative_root/$SYSTEM_ID"
    done
  fi
fi

# Remove non-secret excluded paths from the temporary assembly only.
while IFS= read -r -d '' directory; do
  rm -rf "$directory"
done < <(find "$STAGING" -depth -type d \( \
  -name .git -o -name __MACOSX -o -name __pycache__ -o \
  -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache -o \
  -name .venv -o -name venv -o -name env -o -name node_modules -o \
  -name dist -o -name build -o -name coverage -o -name .idea -o -name .vscode \
  \) -print0)

while IFS= read -r -d '' file; do
  case "$(basename "$file")" in
    .DS_Store|Thumbs.db|*.pyc|*.pyo|*.zip|*.tmp|*.temp|*.log|*~)
      rm -f "$file"
      ;;
  esac
done < <(find "$STAGING" -type f -print0)

if [[ -z "$SYSTEM_ID" && -d "$STAGING/data/raw" ]]; then
  while IFS= read -r -d '' file; do
    rm -f "$file"
  done < <(find "$STAGING/data/raw" -type f \( -iname '*.html' -o -iname '*.htm' \) -print0)
fi

: > "$SECRET_LIST"
while IFS= read -r -d '' file; do
  base_name="$(basename "$file")"
  lower_name="$(printf '%s' "$base_name" | tr '[:upper:]' '[:lower:]')"
  case "$lower_name" in
    .env|.env.*|*.pem|*.p12|*.key)
      printf '%s\n' "${file#"$STAGING/"}" >> "$SECRET_LIST"
      ;;
    *credential*|*secret*|*token*)
      relative_file="${file#"$STAGING/"}"
      case "$relative_file" in
        data/raw/manifests/*/raw_html/*.html|data/raw/manifests/*/raw_html/*.htm|data/raw/manifests/*/meta/*.meta.json)
          # TLIDB entity slugs can legitimately contain words such as "Secret".
          ;;
        *)
          printf '%s\n' "$relative_file" >> "$SECRET_LIST"
          ;;
      esac
      ;;
  esac
done < <(find "$STAGING" -type f -print0)

if [[ -s "$SECRET_LIST" ]]; then
  echo "Export aborted: credential-like file paths found:" >&2
  while IFS= read -r relative; do
    printf '%s\n' "- $relative" >&2
  done < "$SECRET_LIST"
  exit 1
fi

BRANCH="unknown"
COMMIT="unknown"
DIRTY="unknown"
if command -v git >/dev/null 2>&1 && git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  BRANCH="$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || true)"
  [[ -n "$BRANCH" ]] || BRANCH="unknown"
  COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
  [[ -n "$COMMIT" ]] || COMMIT="unknown"
  if [[ -n "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null || true)" ]]; then
    DIRTY="yes"
  else
    DIRTY="no"
  fi
fi

TOP_LEVEL_DIRS="$(find "$STAGING" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | LC_ALL=C sort)"
FILE_COUNT="$(( $(find "$STAGING" -type f | wc -l | tr -d ' ') + 1 ))"
GENERATED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
REPO_NAME="$(basename "$REPO_ROOT")"
RAW_HTML_COUNT="0"
META_COUNT="0"
STRUCTURED_COUNT="0"
if [[ -n "$SYSTEM_ID" ]]; then
  if [[ -d "$STAGING/data/raw/manifests/$SYSTEM_ID/raw_html" ]]; then
    RAW_HTML_COUNT="$(find "$STAGING/data/raw/manifests/$SYSTEM_ID/raw_html" -type f \( -iname '*.html' -o -iname '*.htm' \) | wc -l | tr -d ' ')"
  fi
  if [[ -d "$STAGING/data/raw/manifests/$SYSTEM_ID/meta" ]]; then
    META_COUNT="$(find "$STAGING/data/raw/manifests/$SYSTEM_ID/meta" -type f -name '*.meta.json' | wc -l | tr -d ' ')"
  fi
  if [[ -d "$STAGING/data/structured" ]]; then
    STRUCTURED_COUNT="$(find "$STAGING/data/structured" -type f | wc -l | tr -d ' ')"
  fi
fi

if [[ -z "$SYSTEM_ID" ]]; then
  {
    echo "AI Source Manifest"
    echo "Generated at: $GENERATED_AT"
    echo "Repository: $REPO_NAME"
    echo "Git branch: $BRANCH"
    echo "Git commit: $COMMIT"
    echo "Working tree has uncommitted changes: $DIRTY"
    echo "ZIP file count: $FILE_COUNT"
    echo "Included top-level directories:"
    if [[ -n "$TOP_LEVEL_DIRS" ]]; then
      while IFS= read -r directory; do
        echo "- $directory"
      done <<< "$TOP_LEVEL_DIRS"
    fi
    echo "Excluded: raw HTML, Git metadata, caches, virtual environments, previous exports, credentials"
    echo "Raw HTML included: no"
  } > "$STAGING/AI_SOURCE_MANIFEST.txt"
else
  {
    echo "AI Source Manifest"
    echo "Bundle type: system"
    echo "System ID: $SYSTEM_ID"
    echo "System status: $SYSTEM_STATUS"
    echo "System index URL: $SYSTEM_INDEX_URL"
    echo "System manifest: $SYSTEM_MANIFEST_REL"
    echo "Raw HTML included: yes"
    echo "Raw page count: $RAW_HTML_COUNT"
    echo "Meta count: $META_COUNT"
    echo "Structured files: $STRUCTURED_COUNT"
    echo "Generated at: $GENERATED_AT"
    echo "Repository: $REPO_NAME"
    echo "Git branch: $BRANCH"
    echo "Git commit: $COMMIT"
    echo "Working tree dirty: $DIRTY"
    echo "ZIP file count: $FILE_COUNT"
    echo "This bundle is intended for focused AI research of one TLIDB system."
  } > "$STAGING/AI_SOURCE_MANIFEST.txt"
fi

(
  cd "$STAGING"
  zip -qr "$OUTPUT" .
)

SIZE="$(du -h "$OUTPUT" | awk '{print $1}')"
if command -v shasum >/dev/null 2>&1; then
  SHA256="$(shasum -a 256 "$OUTPUT" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  SHA256="$(sha256sum "$OUTPUT" | awk '{print $1}')"
else
  SHA256="unknown"
fi

if [[ -z "$SYSTEM_ID" ]]; then
  echo "Export complete:"
  echo "$OUTPUT"
  echo
  echo "Size:"
  echo "$SIZE"
  echo
  echo "Files:"
  echo "$FILE_COUNT"
  echo
  echo "SHA-256:"
  echo "$SHA256"
  echo
  echo "Excluded:"
  echo "- raw HTML"
  echo "- Git metadata"
  echo "- caches"
  echo "- virtual environments"
  echo "- previous exports"
  echo "- credentials"
else
  echo "System export complete:"
  echo "$OUTPUT"
  echo
  echo "System:"
  echo "$SYSTEM_ID"
  echo
  echo "Raw HTML:"
  echo "$RAW_HTML_COUNT"
  echo
  echo "Meta:"
  echo "$META_COUNT"
  echo
  echo "Structured:"
  echo "$STRUCTURED_COUNT"
  echo
  echo "Size:"
  echo "$SIZE"
  echo
  echo "Files:"
  echo "$FILE_COUNT"
  echo
  echo "SHA-256:"
  echo "$SHA256"
fi
