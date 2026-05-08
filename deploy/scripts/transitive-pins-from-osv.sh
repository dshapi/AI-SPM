#!/usr/bin/env bash
# deploy/scripts/transitive-pins-from-osv.sh
# ─────────────────────────────────────────────────────────────────────────────
# Read an osv-scanner JSON report and emit a block of explicit pip pins that
# fix every reported vulnerability. Drop the output at the bottom of the
# corresponding requirements.txt.
#
# Why: when a top-level package (apache-flink, tensorflow, ...) pulls in
# vulnerable transitives, you can't always upgrade the parent without a
# breaking-change rabbit hole. Explicit transitive pins override the parent's
# constraints — pip will pick the pinned version even though apache-flink
# would have picked an older one.
#
# Usage:
#   bash deploy/scripts/transitive-pins-from-osv.sh \
#     deploy/audit-reports/latest/osv-scanner/services_flink_pyjob_requirements.txt.json
#
# Output (stdout): a comment header + one line per vulnerable package, pinned
# to the highest fixed version that osv-scanner reports.
#
# Pipe to >> the requirements.txt:
#   bash deploy/scripts/transitive-pins-from-osv.sh <json> \
#     >> services/flink_pyjob/requirements.txt
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <osv-scanner-report.json>" >&2
  exit 2
fi

REPORT="$1"
[[ -f "$REPORT" ]] || { echo "Not a file: $REPORT" >&2; exit 2; }

command -v jq >/dev/null 2>&1 || { echo "jq required" >&2; exit 2; }

DATE="$(date -u +%Y-%m-%d)"

cat <<EOF

# ─── Transitive CVE fixes — auto-generated $DATE ────────────────────────────
# Source: $REPORT
# These pins override transitive resolutions to bring vulnerable packages
# forward to a fixed version. Re-generate after each audit cycle.
EOF

# For each vulnerable package: pick the highest fixed version across all CVEs
# that affect it, then emit  package>=<that-version>  with CVE IDs as a comment.
jq -r '
  .results[]?.packages[]?
  | select(.vulnerabilities | length > 0)
  | {
      name: .package.name,
      current: .package.version,
      cves: [.vulnerabilities[].id] | unique,
      fixes: [
        .vulnerabilities[]
        | .affected[]?.ranges[]?.events[]?.fixed
      ] | map(select(. != null))
    }
  | select(.fixes | length > 0)
  | "\(.name)>=" + (.fixes | sort_by(split(".") | map(tonumber? // 0)) | last)
    + "  # was \(.current); fixes: " + (.cves | join(", "))
' "$REPORT" \
  | sort -u
