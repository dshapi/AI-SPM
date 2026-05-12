#!/usr/bin/env bash
# Bootstrap Keycloak realm, client, and roles for AISPM.
# All vars are injected by compose.yml / Helm environment block — no .env file.
set -euo pipefail

KC_URL="${KEYCLOAK_URL:-http://localhost:8180}"
ADMIN_USER="${KEYCLOAK_ADMIN}"       # Must be set in compose.yml/Helm — no default
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD}"  # Must be set in compose.yml/Helm — no default
REALM="aispm"
CLIENT_ID="aispm-ui"
CLIENT_SECRET="${AISPM_CLIENT_SECRET}"  # Must be set in compose.yml keycloak service env block
KCADM="/opt/keycloak/bin/kcadm.sh"

echo "Waiting for Keycloak at $KC_URL ..."
RETRIES=0; MAX_RETRIES=60
until curl -sf "$KC_URL/health/ready" > /dev/null; do
  sleep 2; RETRIES=$((RETRIES+1))
  [ "$RETRIES" -ge "$MAX_RETRIES" ] && { echo "ERROR: Keycloak did not become ready after $((MAX_RETRIES*2))s."; exit 1; }
done
echo "Keycloak is ready."

# Authenticate kcadm
echo "Authenticating kcadm as $ADMIN_USER ..."
"$KCADM" config credentials \
  --server "$KC_URL" --realm master \
  --user "$ADMIN_USER" --password "$ADMIN_PASS"

# Create realm (idempotent)
echo "Creating realm '$REALM' (if not exists) ..."
"$KCADM" get realms/"$REALM" > /dev/null 2>&1 || \
  "$KCADM" create realms \
    -s realm="$REALM" -s enabled=true -s displayName="AISPM"

# Create confidential client (idempotent)
echo "Creating client '$CLIENT_ID' (if not exists) ..."
CLIENT_EXISTS=$("$KCADM" get clients -r "$REALM" \
  --fields clientId -q clientId="$CLIENT_ID" 2>/dev/null | grep -c "\"$CLIENT_ID\"" || true)
if [ "$CLIENT_EXISTS" -eq 0 ]; then
  "$KCADM" create clients -r "$REALM" \
    -s clientId="$CLIENT_ID" \
    -s secret="$CLIENT_SECRET" \
    -s publicClient=false \
    # directAccessGrantsEnabled: required for ROPC flow (dev/test login). Set false in prod if using authorization_code only.
    -s directAccessGrantsEnabled=true \
    -s 'redirectUris=["http://localhost:5173/*","http://aispm.local/*"]' \
    -s 'webOrigins=["http://localhost:5173","http://aispm.local"]'
fi

# Create realm roles (idempotent)
echo "Creating realm roles (if not exists) ..."
for ROLE in "spm:admin" "spm:auditor" "spm:viewer" "spm:security-analyst"; do
  "$KCADM" get roles -r "$REALM" --fields name \
    | grep -q "\"$ROLE\"" || \
    "$KCADM" create roles -r "$REALM" -s name="$ROLE"
done

echo "Realm '$REALM' configured."
