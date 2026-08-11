#!/bin/bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "TLIDB Local Mirror:"
echo "http://localhost:8000/local_wiki/ss13/site/cn/"
echo ""
echo "Local Search:"
echo "http://localhost:8000/local_wiki/ss13/site/_local/search/"
exec python3 -m http.server 8000
