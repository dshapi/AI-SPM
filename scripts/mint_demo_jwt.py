#!/usr/bin/env python3
"""Mint a demo JWT for testing. Uses RS256 private key."""
import argparse, time, os, sys
import jwt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sub", default="user-demo-1")
    parser.add_argument("--tenant", default="t1")
    parser.add_argument("--roles", nargs="*", default=["user"])
    parser.add_argument("--scopes", nargs="*", default=[
        "calendar:read","calendar:write","gmail:read","gmail:send",
        "memory:read","memory:write","memory:read:longterm","memory:delete",
        "file:read","db:read",
    ])
    parser.add_argument("--ttl", type=int, default=3600)
    parser.add_argument("--admin", action="store_true", help="Add spm:admin role")
    args = parser.parse_args()

    key_path = os.getenv("JWT_PRIVATE_KEY_PATH", "/keys/private.pem")
    issuer = os.getenv("JWT_ISSUER", "cpm-platform")

    if args.admin:
        args.roles = list(set(args.roles + ["spm:admin"]))

    try:
        with open(key_path) as f:
            private_key = f.read()
    except FileNotFoundError:
        sys.exit(f"ERROR: private key not found at {key_path}. Run startup orchestrator first.")

    now = int(time.time())
    payload = {
        "sub": args.sub, "iss": issuer, "iat": now, "exp": now + args.ttl,
        "tenant_id": args.tenant, "roles": args.roles, "scopes": args.scopes,
    }
    print(jwt.encode(payload, private_key, algorithm="RS256"))

if __name__ == "__main__":
    main()
