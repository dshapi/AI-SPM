#!/usr/bin/env python3
"""
Deprecated shim — seeding moved to the API.

The initial 18-integration seed is now applied by calling:

    POST /integrations/bootstrap    (on spm-api:8092, Bearer <admin JWT>)

This replaces the old on-disk seed script.  Services fetch their managed
configuration directly from spm-db at startup via
`platform_shared.integration_config.hydrate_env_from_db()` — there is no
longer an `.env.integrations` file to regenerate.

Rotation flow (post-migration):
    Admin UI → Integrations → Configure  (writes directly to DB)
    docker compose restart api guard-model threat-hunting-agent garak-runner

This file exists only so CI pipelines that referenced it by path fail loud
instead of silently running stale logic.
"""
import sys

print(
    "scripts/seed_integrations.py has been removed.\n"
    "Seed the integrations DB by calling POST /api/spm/integrations/bootstrap\n"
    "with an admin JWT.  See services/spm_api/integrations_seed_data.py for\n"
    "the seed content and platform_shared/integration_config.py for the\n"
    "direct-DB hydration flow that replaced .env.integrations.",
    file=sys.stderr,
)
sys.exit(2)
