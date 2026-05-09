#!/usr/bin/env bash
# Bootstrap Keycloak realm, client, and roles for AISPM.
# All vars are injected by compose.yml / Helm environment block — no .env file.
set -euo pipefail

KC_URL="${KEYCLOAK_URL:-http://localhost:8180}"
ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
REALM="aispm"
CLIENT_ID="aispm-ui"
CLIENT_SECRET="${AISPM_CLIENT_SECRET}"  # Must be set in compose.yml keycloak service env block

echo "Waiting for Keycloak at $KC_URL ..."
until curl -sf "$KC_URL/health/ready" > /dev/null; do sleep 2; done

# Authenticate kcadm
/opt/keycloak/bin/kcadm.sh config credentials \
  --server "$KC_URL" --realm master \
  --user "$ADMIN_USER" --password "$ADMIN_PASS"

# Create realm (idempotent)
/opt/keycloak/bin/kcadm.sh get realms/"$REALM" > /dev/null 2>&1 || \
  /opt/keycloak/bin/kcadm.sh create realms \
    -s realm="$REALM" -s enabled=true -s displayName="AISPM"

# Create confidential client (idempotent)
CLIENT_EXISTS=$(/opt/keycloak/bin/kcadm.sh get clients -r "$REALM" \
  --fields clientId -q clientId="$CLIENT_ID" 2>/dev/null | grep -c "$CLIENT_ID" || true)
if [ "$CLIENT_EXISTS" -eq 0 ]; then
  /opt/keycloak/bin/kcadm.sh create clients -r "$REALM" \
    -s clientId="$CLIENT_ID" \
    -s secret="$CLIENT_SECRET" \
    -s publicClient=false \
    -s directAccessGrantsEnabled=true \
    -s 'redirectUris=["http://localhost:5173/*","http://aispm.local/*"]' \
    -s 'webOrigins=["http://localhost:5173","http://aispm.local"]'
fi

# Create realm roles (idempotent)
for ROLE in "spm:admin" "spm:auditor" "spm:viewer"; do
  /opt/keycloak/bin/kcadm.sh get roles -r "$REALM" --fields name \
    | grep -q "\"$ROLE\"" || \
    /opt/keycloak/bin/kcadm.sh create roles -r "$REALM" -s name="$ROLE"
done

echo "Realm '$REALM' configured."
