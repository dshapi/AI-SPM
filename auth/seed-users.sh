#!/usr/bin/env bash
# Seed demo users into the Keycloak aispm realm.
# All values injected by compose.yml / Helm — no .env file.
set -euo pipefail

KC_URL="${KEYCLOAK_URL:-http://localhost:8180}"
ADMIN_USER="${KEYCLOAK_ADMIN}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD}"
REALM="aispm"
KCADM="/opt/keycloak/bin/kcadm.sh"

echo "Authenticating with Keycloak..."
"$KCADM" config credentials \
  --server "$KC_URL" --realm master \
  --user "$ADMIN_USER" --password "$ADMIN_PASS"

create_user() {
  local username="$1" password="$2" role="$3" email="$4"
  EXISTS=$("$KCADM" get users -r "$REALM" --fields username -q username="$username" 2>/dev/null \
    | grep -c "\"$username\"" || true)
  if [ "$EXISTS" -eq 0 ]; then
    "$KCADM" create users -r "$REALM" \
      -s username="$username" -s email="$email" \
      -s enabled=true -s emailVerified=true \
      -s "credentials=[{\"type\":\"password\",\"value\":\"$password\",\"temporary\":false}]"
    echo "Created: $username"
  else
    echo "Exists: $username"
  fi
  "$KCADM" add-roles -r "$REALM" --uusername "$username" --rolename "$role" 2>/dev/null || true
}

create_user "admin@aispm.local"    "${SEED_ADMIN_PASSWORD}"            "spm:admin"            "admin@aispm.local"
create_user "auditor@aispm.local"  "${SEED_AUDITOR_PASSWORD}"          "spm:auditor"          "auditor@aispm.local"
create_user "viewer@aispm.local"   "${SEED_VIEWER_PASSWORD}"           "spm:viewer"           "viewer@aispm.local"
create_user "analyst@aispm.local"  "${SEED_ANALYST_PASSWORD:-analyst}" "spm:security-analyst" "analyst@aispm.local"

echo "Keycloak user seeding complete."
