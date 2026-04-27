"""
Integrations bootstrap seed data.

One-shot reference data used by the POST /integrations/bootstrap endpoint.
Lives in-process (not on disk as a standalone script) so the DB can be
seeded from the running spm-api.

On first bootstrap the endpoint reads live secrets from its own process
environment (ANTHROPIC_API_KEY etc — still carried in .env until the
operator strips them) and writes them into the `integration_credentials`
table.  Subsequent calls are idempotent upserts keyed by `external_id`.

This is the single source of truth for the "initial 21 integrations";
the prior /scripts/seed_integrations.py has been removed.

Every row carries a ``connector_type`` (e.g. "postgres", "kafka") that
matches a key in ``connector_registry.CONNECTOR_TYPES``.  We inject it
in a normalize pass at the bottom of ``build_seed()`` rather than
hand-typing it on every dict, keyed off the integration's ``name`` via
``_NAME_TO_CONNECTOR_TYPE`` — same table the Alembic 004 backfill uses.

Env-var → DB mapping (for the /integrations/env endpoint):

    ANTHROPIC_API_KEY            → int-003.credentials.api_key
    ANTHROPIC_MODEL              → int-003.config.model
    TAVILY_API_KEY               → int-016.credentials.api_key
    GROQ_BASE_URL                → int-017.config.base_url
    LLM_MODEL                    → int-017.config.model
    GUARD_PROMPT_MODE            → int-017.config.guard_prompt_mode
    OLLAMA_KEEP_ALIVE            → int-017.config.keep_alive
    GARAK_INTERNAL_SECRET        → int-018.credentials.shared_secret
    SPM_INTERNAL_BOOTSTRAP_SECRET→ int-018.credentials.internal_bootstrap_secret

SPM_INTERNAL_BOOTSTRAP_SECRET is co-located with GARAK_INTERNAL_SECRET on
int-018 because both are "internal service-to-service" secrets: Garak uses
the shared_secret to post findings back to `api`, and the bootstrap secret
is used by sibling containers to authenticate the internal GET
/integrations/env call at startup.  Keeping them on the same integration
makes rotation a single Configure action rather than two.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def _envget(key: str) -> Optional[str]:
    """Read an env var; returns None for empty/unset (not '' so the caller
    can distinguish 'not configured' from 'configured to empty string')."""
    v = os.getenv(key)
    return v if v else None


# ( external_id , kind , key_in_db , env_var_name )
# kind ∈ {"config", "credential"}  (credential key = credential_type column)
# Lowercased integration.name → connector_type registry key.  Same
# table as in Alembic migration 004 — duplicated here so ``build_seed()``
# is self-contained and doesn't need a DB round-trip.  Keep in sync.
_NAME_TO_CONNECTOR_TYPE: Dict[str, str] = {
    "openai":             "openai",
    "azure openai":       "azure_openai",
    "anthropic":          "anthropic",
    "amazon bedrock":     "bedrock",
    "google vertex ai":   "vertex",
    "splunk":             "splunk",
    "microsoft sentinel": "sentinel",
    "jira":               "jira",
    "servicenow":         "servicenow",
    "slack":              "slack",
    "okta":               "okta",
    "entra id":           "entra",
    "amazon s3":          "s3",
    "confluence":         "confluence",
    "kafka":              "kafka",
    "tavily":             "tavily",
    "ollama":             "ollama",
    "garak":              "garak",
    "apache flink":       "flink",
    "flink":              "flink",
    "postgresql":         "postgres",
    "postgres":           "postgres",
    "redis":              "redis",
    # int-022 — meta integration that tells spm-llm-proxy which
    # upstream LLM to route agent runtime calls through. Keyed by the
    # full display name (lower-cased); kept here so the seed normalize
    # pass populates connector_type even if a future seed forgets the
    # explicit field.
    "ai-spm agent runtime control plane (mcp)": "agent-runtime",
}


ENV_EXPORT_MAP: List[tuple] = [
    ("int-003", "credential", "api_key",                   "ANTHROPIC_API_KEY"),
    ("int-003", "config",     "model",                     "ANTHROPIC_MODEL"),
    ("int-016", "credential", "api_key",                   "TAVILY_API_KEY"),
    ("int-017", "config",     "base_url",                  "GROQ_BASE_URL"),
    ("int-017", "config",     "model",                     "LLM_MODEL"),
    ("int-017", "config",     "guard_prompt_mode",         "GUARD_PROMPT_MODE"),
    ("int-017", "config",     "keep_alive",                "OLLAMA_KEEP_ALIVE"),
    ("int-018", "credential", "shared_secret",             "GARAK_INTERNAL_SECRET"),
    ("int-018", "credential", "internal_bootstrap_secret", "SPM_INTERNAL_BOOTSTRAP_SECRET"),
]


def build_seed() -> List[Dict[str, Any]]:
    """Return the 21-entry seed list.  Values that bootstrap from env vars
    are resolved at call time so rotating the env between bootstrap runs
    pushes the new value into the DB.

    Every returned dict has ``connector_type`` populated via a name-based
    lookup — operators pointing a custom integration at a registry key
    should set ``connector_type`` on the dict explicitly (overrides win)."""
    rows: List[Dict[str, Any]] = [
        # ── AI Providers ──
        {
            "external_id": "int-001", "name": "OpenAI", "abbrev": "OA",
            "category": "AI Providers", "status": "Healthy", "auth_method": "API Key",
            "owner": "raj.patel", "owner_display": "Raj Patel",
            "environment": "Production", "enabled": True,
            "description": "Direct API integration with OpenAI for GPT-4 and GPT-3.5 model families. Supports completions, embeddings, and function calling for production agents.",
            "vendor": "OpenAI, Inc.",
            "tags": ["gpt-4o", "embeddings"],
            "config": {},
            "connection": {
                "last_sync": "4m ago", "last_sync_full": "Apr 8 · 14:28 UTC",
                "last_failed_sync": None, "avg_latency": "218ms", "uptime": "99.98%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "Never (static key)",
                "scopes": ["completions:write", "models:read", "embeddings:write", "usage:read"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Execute model completions", True),
                ("Generate embeddings",       True),
                ("Read model metadata",       True),
                ("Ingest runtime events",     True),
                ("Send notifications",        False),
                ("Execute ticket actions",    False),
            ],
            "activity": [
                ("Apr 8 · 14:28 UTC", "API key validated",              "Success"),
                ("Apr 8 · 08:00 UTC", "Daily health check passed",      "Success"),
                ("Apr 7 · 14:28 UTC", "API key validated",              "Success"),
                ("Apr 5 · 11:00 UTC", "Rate limit warning — 85% quota", "Warning"),
                ("Apr 3 · 14:28 UTC", "API key validated",              "Success"),
            ],
            "workflows": {
                "playbooks": ["Prompt Injection Auto-Response", "Model Drift Auto-Containment"],
                "alerts":    ["Model Rate Limit", "API Error Spike"],
                "policies":  ["Prompt-Guard v3", "Output-Guard v2"],
                "cases":     ["CASE-1042", "CASE-1051"],
            },
            "credentials": [{"type": "api_key", "name": "Primary API key"}],
        },
        {
            "external_id": "int-002", "name": "Azure OpenAI", "abbrev": "Az",
            "category": "AI Providers", "status": "Healthy", "auth_method": "API Key",
            "owner": "raj.patel", "owner_display": "Raj Patel",
            "environment": "Production", "enabled": True,
            "description": "Azure-hosted OpenAI deployment for enterprise compliance. Supports GPT-4 Turbo within the EU data boundary.",
            "vendor": "Microsoft Azure",
            "tags": ["gpt-4-turbo", "eu-boundary"],
            "config": {},
            "connection": {
                "last_sync": "12m ago", "last_sync_full": "Apr 8 · 14:20 UTC",
                "last_failed_sync": None, "avg_latency": "312ms", "uptime": "99.94%",
                "health_history": ["ok","ok","ok","ok","ok","warn","ok","ok","ok","ok","ok","ok","ok","ok"],
            },
            "auth": {
                "token_expiry": "Never (static key)",
                "scopes": ["completions:write", "models:read", "embeddings:write"],
                "missing_scopes": ["fine-tune:read"], "setup_progress": None,
            },
            "coverage": [
                ("Execute model completions",   True),
                ("Generate embeddings",         True),
                ("EU data boundary compliance", True),
                ("Fine-tune model access",      False),
                ("Send notifications",          False),
            ],
            "activity": [
                ("Apr 8 · 14:20 UTC", "Health check passed",            "Success"),
                ("Apr 6 · 09:00 UTC", "Endpoint latency spike — 890ms", "Warning"),
                ("Apr 5 · 14:20 UTC", "API key validated",              "Success"),
            ],
            "workflows": {
                "playbooks": ["Daily Security Posture Digest"],
                "alerts": ["API Error Spike"],
                "policies": ["EU-Compliance-Guard"], "cases": [],
            },
            "credentials": [{"type": "api_key", "name": "Primary API key"}],
        },
        {
            "external_id": "int-003", "name": "Anthropic", "abbrev": "An",
            "category": "AI Providers", "status": "Healthy", "auth_method": "API Key",
            "owner": "raj.patel", "owner_display": "Raj Patel",
            "environment": "Production", "enabled": True,
            "description": "Claude model family API for analysis agents and content safety evaluation. The primary model name is configurable from the Configure modal.",
            "vendor": "Anthropic, PBC",
            "tags": ["claude", "safety-eval"],
            "config": {"model": _envget("ANTHROPIC_MODEL") or "claude-sonnet-4-6"},
            "connection": {
                "last_sync": "8m ago", "last_sync_full": "Apr 8 · 14:24 UTC",
                "last_failed_sync": None, "avg_latency": "245ms", "uptime": "99.99%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "Never (static key)",
                "scopes": ["messages:write", "models:read"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Execute model completions", True),
                ("Content safety evaluation", True),
                ("Ingest runtime events",     True),
                ("Generate embeddings",       False),
            ],
            "activity": [
                ("Apr 8 · 14:24 UTC", "Health check passed", "Success"),
                ("Apr 7 · 14:24 UTC", "API key validated",   "Success"),
            ],
            "workflows": {
                "playbooks": [], "alerts": ["Safety Eval Failed"],
                "policies": ["Content-Safety-Guard"], "cases": [],
            },
            "credentials": [{"type": "api_key", "name": "Primary API key",
                             "env_var": "ANTHROPIC_API_KEY"}],
        },
        {
            "external_id": "int-004", "name": "Amazon Bedrock", "abbrev": "Bk",
            "category": "AI Providers", "status": "Healthy", "auth_method": "IAM Role",
            "owner": "mike.torres", "owner_display": "Mike Torres",
            "environment": "Production", "enabled": True,
            "description": "AWS Bedrock via IAM role for multi-model inference including Titan Embeddings and Claude 3 on-demand. Governed by AWS SCP policies.",
            "vendor": "Amazon Web Services",
            "tags": ["titan", "claude-bedrock", "iam"],
            "config": {},
            "connection": {
                "last_sync": "6m ago", "last_sync_full": "Apr 8 · 14:26 UTC",
                "last_failed_sync": None, "avg_latency": "198ms", "uptime": "99.96%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "IAM — no expiry",
                "scopes": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream",
                           "bedrock:ListFoundationModels"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Execute model completions", True),
                ("Generate embeddings",       True),
                ("Stream responses",          True),
                ("List available models",     True),
                ("Send notifications",        False),
            ],
            "activity": [
                ("Apr 8 · 14:26 UTC", "IAM role validation passed", "Success"),
                ("Apr 8 · 09:30 UTC", "Daily health check passed",  "Success"),
                ("Apr 7 · 14:26 UTC", "IAM role validation passed", "Success"),
            ],
            "workflows": {
                "playbooks": ["Model Drift Auto-Containment"],
                "alerts": [], "policies": ["AWS-Governance-Guard"], "cases": [],
            },
            "credentials": [{"type": "iam_role_arn", "name": "IAM role ARN"}],
        },
        {
            "external_id": "int-005", "name": "Google Vertex AI", "abbrev": "GV",
            "category": "AI Providers", "status": "Warning", "auth_method": "Service Account",
            "owner": "raj.patel", "owner_display": "Raj Patel",
            "environment": "Staging", "enabled": True,
            "description": "Google Cloud Vertex AI service account integration for Gemini models. Currently in staging — service account key rotation is overdue (expires in 7 days).",
            "vendor": "Google Cloud",
            "tags": ["gemini", "vertex", "staging"],
            "config": {},
            "connection": {
                "last_sync": "2h ago", "last_sync_full": "Apr 8 · 12:30 UTC",
                "last_failed_sync": "Apr 7 · 09:00 UTC",
                "avg_latency": "380ms", "uptime": "97.20%",
                "health_history": ["ok","ok","ok","warn","ok","ok","err","ok","warn","ok","ok","ok","warn","ok"],
            },
            "auth": {
                "token_expiry": "Expires Apr 15, 2026 — 7 days",
                "scopes": ["aiplatform.endpoints.predict", "aiplatform.models.list"],
                "missing_scopes": ["aiplatform.models.delete", "logging.logEntries.create"],
                "setup_progress": None,
            },
            "coverage": [
                ("Execute model completions", True),
                ("List available models",     True),
                ("Generate embeddings",       False),
                ("Write audit logs",          False),
                ("Ingest runtime events",     False),
            ],
            "activity": [
                ("Apr 8 · 12:30 UTC", "Health check — elevated latency 380ms", "Warning"),
                ("Apr 7 · 09:00 UTC", "Service account key expiry warning",    "Warning"),
                ("Apr 6 · 12:30 UTC", "Health check passed",                   "Success"),
                ("Apr 5 · 08:00 UTC", "Token rotation recommended",            "Warning"),
            ],
            "workflows": {
                "playbooks": [], "alerts": ["Credential Expiry Warning"],
                "policies": [], "cases": [],
            },
            "credentials": [{"type": "service_account_json", "name": "Service account key"}],
        },

        # ── Security / SIEM ──
        {
            "external_id": "int-006", "name": "Splunk", "abbrev": "Sp",
            "category": "Security / SIEM", "status": "Error", "auth_method": "API Key",
            "owner": "sarah.chen", "owner_display": "Sarah Chen",
            "environment": "Production", "enabled": True,
            "description": "Splunk SIEM integration for forwarding AI security events, policy violations, and audit logs via HEC endpoint. Failing due to expired token.",
            "vendor": "Splunk Inc.",
            "tags": ["hec", "siem", "audit"],
            "config": {},
            "connection": {
                "last_sync": "1h ago", "last_sync_full": "Apr 8 · 13:00 UTC",
                "last_failed_sync": "Apr 8 · 13:01 UTC",
                "avg_latency": None, "uptime": "91.20%",
                "health_history": ["ok","ok","ok","ok","ok","ok","ok","err","ok","ok","err","err","err","err"],
            },
            "auth": {
                "token_expiry": "Expired Apr 7, 2026",
                "scopes": ["hec:write"],
                "missing_scopes": ["search:read", "indexes:list"],
                "setup_progress": None,
            },
            "coverage": [
                ("Forward security events",    True),
                ("Write audit logs",           True),
                ("Forward policy violations",  True),
                ("Query log indexes",          False),
                ("Run saved searches",         False),
            ],
            "activity": [
                ("Apr 8 · 13:01 UTC", "HEC write failed — token expired",   "Error"),
                ("Apr 8 · 13:00 UTC", "Connection attempt failed",          "Error"),
                ("Apr 7 · 16:44 UTC", "Token rotation failed — 401",        "Error"),
                ("Apr 6 · 18:00 UTC", "Last successful event forward",      "Success"),
                ("Apr 6 · 11:00 UTC", "Admin updated HEC endpoint URL",     "Info"),
            ],
            "workflows": {
                "playbooks": ["Prompt Injection Auto-Response", "PII Exfiltration Escalation",
                              "Daily Security Posture Digest"],
                "alerts": [], "policies": [], "cases": ["CASE-1042"],
            },
            "credentials": [{"type": "api_key", "name": "HEC token"}],
        },
        {
            "external_id": "int-007", "name": "Microsoft Sentinel", "abbrev": "MS",
            "category": "Security / SIEM", "status": "Healthy", "auth_method": "Service Account",
            "owner": "sarah.chen", "owner_display": "Sarah Chen",
            "environment": "Production", "enabled": True,
            "description": "Microsoft Sentinel workspace for AI threat intelligence ingestion and SOAR playbook triggers, connected via service principal.",
            "vendor": "Microsoft Azure",
            "tags": ["sentinel", "soar", "azure"],
            "config": {},
            "connection": {
                "last_sync": "18m ago", "last_sync_full": "Apr 8 · 14:14 UTC",
                "last_failed_sync": None, "avg_latency": "290ms", "uptime": "99.90%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "Service principal — auto-renewed",
                "scopes": ["SecurityInsights/alertRules/write",
                           "SecurityInsights/incidents/read",
                           "SecurityInsights/watchlists/read"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Ingest AI security incidents", True),
                ("Trigger SOAR playbooks",       True),
                ("Read threat intelligence",     True),
                ("Write custom analytics rules", True),
                ("Forward raw events",           False),
            ],
            "activity": [
                ("Apr 7 · 22:15 UTC", "Alert ingestion reconnected", "Success"),
                ("Apr 7 · 14:14 UTC", "Health check passed",         "Success"),
                ("Apr 6 · 14:14 UTC", "Health check passed",         "Success"),
            ],
            "workflows": {
                "playbooks": [], "alerts": ["SIEM Alert Forwarding"],
                "policies": [], "cases": [],
            },
            "credentials": [{"type": "service_account_json", "name": "Service principal"}],
        },

        # ── Ticketing / Workflow ──
        {
            "external_id": "int-008", "name": "Jira", "abbrev": "Ji",
            "category": "Ticketing / Workflow", "status": "Healthy", "auth_method": "API Key",
            "owner": "alex.kim", "owner_display": "Alex Kim",
            "environment": "Production", "enabled": True,
            "description": "Atlassian Jira for automatic ticket creation from security cases with bi-directional status sync.",
            "vendor": "Atlassian",
            "tags": ["jira", "ticketing"],
            "config": {},
            "connection": {
                "last_sync": "8m ago", "last_sync_full": "Apr 8 · 08:00 UTC",
                "last_failed_sync": None, "avg_latency": "175ms", "uptime": "99.95%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "Never (API token)",
                "scopes": ["read:jira-work", "write:jira-work", "read:jira-user"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Create security tickets", True),
                ("Update ticket status",    True),
                ("Read assignee info",      True),
                ("Attach evidence files",   True),
                ("Delete tickets",          False),
            ],
            "activity": [
                ("Apr 8 · 08:00 UTC", "Daily sync — 3 tickets updated", "Success"),
                ("Apr 7 · 15:30 UTC", "CASE-1042 → AISPM-891 created",  "Success"),
                ("Apr 7 · 08:00 UTC", "Daily sync completed",           "Success"),
            ],
            "workflows": {
                "playbooks": ["PII Exfiltration Escalation"], "alerts": [],
                "policies": [], "cases": ["CASE-1042", "CASE-1049"],
            },
            "credentials": [{"type": "api_key", "name": "API token"}],
        },
        {
            "external_id": "int-009", "name": "ServiceNow", "abbrev": "SN",
            "category": "Ticketing / Workflow", "status": "Not Configured", "auth_method": "OAuth",
            "owner": "alex.kim", "owner_display": "Alex Kim",
            "environment": "Production", "enabled": False,
            "description": "ServiceNow ITSM integration for enterprise incident management. OAuth app registered — redirect URI and scopes pending.",
            "vendor": "ServiceNow",
            "tags": ["servicenow", "itsm"],
            "config": {},
            "connection": {
                "last_sync": "Never", "last_sync_full": None,
                "last_failed_sync": None, "avg_latency": None, "uptime": None,
                "health_history": [],
            },
            "auth": {
                "token_expiry": "Not authenticated",
                "scopes": [],
                "missing_scopes": ["incident:create", "incident:read", "incident:update", "user:read"],
                "setup_progress": [
                    {"step": 1, "label": "Register OAuth application", "status": "done"},
                    {"step": 2, "label": "Configure redirect URI",     "status": "pending"},
                    {"step": 3, "label": "Grant required scopes",      "status": "pending"},
                    {"step": 4, "label": "Test connection",            "status": "pending"},
                ],
            },
            "coverage": [
                ("Create ITSM incidents",  False),
                ("Update incident status", False),
                ("Attach evidence files",  False),
                ("Read CMDB assets",       False),
            ],
            "activity": [
                ("Apr 5 · 10:00 UTC", "OAuth app registered — redirect pending", "Info"),
                ("Apr 1 · 09:30 UTC", "Integration added by alex.kim",           "Info"),
            ],
            "workflows": {"playbooks": [], "alerts": [], "policies": [], "cases": []},
            "credentials": [{"type": "oauth_token", "name": "OAuth access token"}],
        },

        # ── Messaging / Collab ──
        {
            "external_id": "int-010", "name": "Slack", "abbrev": "Sl",
            "category": "Messaging / Collab", "status": "Warning", "auth_method": "OAuth",
            "owner": "sarah.chen", "owner_display": "Sarah Chen",
            "environment": "Production", "enabled": True,
            "description": "Slack workspace integration for security alert notifications and daily posture digest delivery. Webhook delivery intermittently timing out.",
            "vendor": "Salesforce / Slack",
            "tags": ["slack", "notifications", "webhook"],
            "config": {},
            "connection": {
                "last_sync": "15m ago", "last_sync_full": "Apr 8 · 14:17 UTC",
                "last_failed_sync": "Apr 8 · 13:00 UTC",
                "avg_latency": "145ms", "uptime": "96.80%",
                "health_history": ["ok","ok","ok","ok","warn","ok","ok","warn","ok","ok","err","ok","ok","warn"],
            },
            "auth": {
                "token_expiry": "OAuth token — auto-refresh",
                "scopes": ["chat:write", "channels:read", "incoming-webhook"],
                "missing_scopes": ["files:write"], "setup_progress": None,
            },
            "coverage": [
                ("Send channel notifications", True),
                ("Post incident updates",      True),
                ("Deliver daily digest",       True),
                ("Attach report files",        False),
                ("Read channel history",       False),
            ],
            "activity": [
                ("Apr 8 · 14:17 UTC", "Webhook delivery — success",                   "Success"),
                ("Apr 8 · 13:00 UTC", "Webhook delivery timeout #security-incidents", "Warning"),
                ("Apr 8 · 11:15 UTC", "PII escalation alert sent",                    "Success"),
                ("Apr 8 · 08:00 UTC", "Daily posture digest delivered",               "Success"),
            ],
            "workflows": {
                "playbooks": ["Prompt Injection Auto-Response", "PII Exfiltration Escalation",
                              "Daily Security Posture Digest", "Model Drift Auto-Containment"],
                "alerts": ["Webhook Failure"], "policies": [], "cases": [],
            },
            "credentials": [{"type": "oauth_token", "name": "OAuth access token"}],
        },

        # ── Identity / Access ──
        {
            "external_id": "int-011", "name": "Okta", "abbrev": "Ok",
            "category": "Identity / Access", "status": "Partial", "auth_method": "OAuth",
            "owner": "mike.torres", "owner_display": "Mike Torres",
            "environment": "Production", "enabled": True,
            "description": "Okta identity provider for user identity validation, trust scoring, and session risk classification. Scope sync is partially configured — missing groups:read.",
            "vendor": "Okta, Inc.",
            "tags": ["okta", "identity", "oauth"],
            "config": {},
            "connection": {
                "last_sync": "11m ago", "last_sync_full": "Apr 8 · 14:21 UTC",
                "last_failed_sync": "Apr 8 · 11:15 UTC",
                "avg_latency": "135ms", "uptime": "98.40%",
                "health_history": ["ok","ok","ok","ok","warn","ok","ok","ok","warn","warn","ok","ok","ok","ok"],
            },
            "auth": {
                "token_expiry": "Refreshed 11m ago — 59m remaining",
                "scopes": ["openid", "profile", "email", "okta.users.read"],
                "missing_scopes": ["okta.groups.read", "okta.logs.read"],
                "setup_progress": [
                    {"step": 1, "label": "Register OAuth application", "status": "done"},
                    {"step": 2, "label": "Configure redirect URI",     "status": "done"},
                    {"step": 3, "label": "Grant required scopes",      "status": "error"},
                    {"step": 4, "label": "Test connection",            "status": "pending"},
                ],
            },
            "coverage": [
                ("Validate user identity",  True),
                ("Read user profiles",      True),
                ("Classify session risk",   True),
                ("Read group memberships",  False),
                ("Read audit logs",         False),
            ],
            "activity": [
                ("Apr 8 · 14:21 UTC", "OAuth token refreshed",            "Success"),
                ("Apr 8 · 11:15 UTC", "Scope sync — groups:read missing", "Warning"),
                ("Apr 7 · 14:21 UTC", "OAuth token refreshed",            "Success"),
                ("Apr 6 · 10:00 UTC", "Scope update by mike.torres",      "Info"),
            ],
            "workflows": {
                "playbooks": [], "alerts": ["Identity Risk Score Alert"],
                "policies": ["Identity-Trust-Guard"], "cases": [],
            },
            "credentials": [{"type": "oauth_token", "name": "OAuth access token"}],
        },
        {
            "external_id": "int-012", "name": "Entra ID", "abbrev": "En",
            "category": "Identity / Access", "status": "Healthy", "auth_method": "OAuth",
            "owner": "mike.torres", "owner_display": "Mike Torres",
            "environment": "Production", "enabled": True,
            "description": "Microsoft Entra ID (Azure AD) for enterprise SSO, group-based access control, and conditional access policy enforcement.",
            "vendor": "Microsoft",
            "tags": ["azure-ad", "entra", "sso"],
            "config": {},
            "connection": {
                "last_sync": "9m ago", "last_sync_full": "Apr 8 · 14:23 UTC",
                "last_failed_sync": None, "avg_latency": "168ms", "uptime": "99.97%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "Auto-renewed — enterprise tenant",
                "scopes": ["User.Read", "Group.Read.All", "Directory.Read.All", "AuditLog.Read.All"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("SSO user authentication",    True),
                ("Read group memberships",     True),
                ("Enforce conditional access", True),
                ("Read audit logs",            True),
                ("Write directory objects",    False),
            ],
            "activity": [
                ("Apr 7 · 14:30 UTC", "OAuth token refreshed",  "Success"),
                ("Apr 7 · 08:00 UTC", "Group sync — 148 users", "Success"),
                ("Apr 6 · 14:30 UTC", "OAuth token refreshed",  "Success"),
            ],
            "workflows": {
                "playbooks": [], "alerts": [],
                "policies": ["Identity-Trust-Guard", "Conditional-Access-Policy"], "cases": [],
            },
            "credentials": [{"type": "oauth_token", "name": "OAuth access token"}],
        },

        # ── Data / Storage ──
        {
            "external_id": "int-013", "name": "Amazon S3", "abbrev": "S3",
            "category": "Data / Storage", "status": "Healthy", "auth_method": "IAM Role",
            "owner": "mike.torres", "owner_display": "Mike Torres",
            "environment": "Production", "enabled": True,
            "description": "S3 bucket integration for evidence artifact storage, audit log export, and RAG document ingestion. Least-privilege IAM policy enforced.",
            "vendor": "Amazon Web Services",
            "tags": ["s3", "storage", "iam"],
            "config": {},
            "connection": {
                "last_sync": "30m ago", "last_sync_full": "Apr 8 · 14:02 UTC",
                "last_failed_sync": None, "avg_latency": "82ms", "uptime": "100%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "IAM — no expiry",
                "scopes": ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Store evidence artifacts", True),
                ("Export audit logs",        True),
                ("Fetch RAG documents",      True),
                ("Manage bucket policies",   False),
            ],
            "activity": [
                ("Apr 8 · 14:02 UTC", "Evidence archive written — CASE-1042", "Success"),
                ("Apr 8 · 08:00 UTC", "Daily log export completed",           "Success"),
                ("Apr 7 · 14:02 UTC", "IAM role validation passed",           "Success"),
            ],
            "workflows": {
                "playbooks": [], "alerts": [], "policies": [],
                "cases": ["CASE-1042", "CASE-1049"],
            },
            "credentials": [{"type": "iam_role_arn", "name": "IAM role ARN"}],
        },
        {
            "external_id": "int-014", "name": "Confluence", "abbrev": "Cf",
            "category": "Data / Storage", "status": "Healthy", "auth_method": "API Key",
            "owner": "alex.kim", "owner_display": "Alex Kim",
            "environment": "Production", "enabled": True,
            "description": "Atlassian Confluence for RAG document ingestion. Security runbooks and knowledge base content indexed for AI agents.",
            "vendor": "Atlassian",
            "tags": ["confluence", "rag", "knowledge-base"],
            "config": {},
            "connection": {
                "last_sync": "1h ago", "last_sync_full": "Apr 8 · 13:30 UTC",
                "last_failed_sync": None, "avg_latency": "210ms", "uptime": "99.88%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "Never (API token)",
                "scopes": ["read:page:confluence", "read:space:confluence", "read:attachment:confluence"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Fetch RAG documents",  True),
                ("Read page content",    True),
                ("List spaces",          True),
                ("Read attachments",     True),
                ("Write pages",          False),
            ],
            "activity": [
                ("Apr 8 · 13:30 UTC", "Sync completed — 14 pages indexed", "Success"),
                ("Apr 7 · 13:30 UTC", "Sync completed — 2 pages updated",  "Success"),
            ],
            "workflows": {"playbooks": [], "alerts": [], "policies": [], "cases": []},
            "credentials": [{"type": "api_key", "name": "API token"}],
        },
        {
            "external_id": "int-015", "name": "Kafka", "abbrev": "Kf",
            "category": "Data / Storage", "status": "Error", "auth_method": "Service Account",
            "owner": "mike.torres", "owner_display": "Mike Torres",
            "environment": "Production", "enabled": True,
            "description": "Apache Kafka for real-time AI event stream ingestion. Consumer group disconnected after broker certificate renewal.",
            "vendor": "Confluent / Apache",
            "tags": ["kafka", "streaming", "events"],
            "config": {
                # Points at the real broker hostname inside the
                # aispm_default docker network (see compose.yml
                # service `kafka-broker`).  The Test button does a TCP
                # dial against this — a placeholder hostname would just
                # surface DNS / timeout noise instead of a useful signal.
                # Override via Configure if your broker lives elsewhere.
                "bootstrap_servers": "kafka-broker:9092",
            },
            "connection": {
                "last_sync": "2d ago", "last_sync_full": "Apr 6 · 22:00 UTC",
                "last_failed_sync": "Apr 7 · 00:00 UTC",
                "avg_latency": None, "uptime": "82.50%",
                "health_history": ["ok","ok","ok","ok","ok","ok","ok","ok","ok","err","err","err","err","err"],
            },
            "auth": {
                "token_expiry": "Service account cert expired",
                "scopes": ["kafka:consumer:read", "kafka:topics:list"],
                "missing_scopes": ["kafka:producer:write"], "setup_progress": None,
            },
            "coverage": [
                ("Ingest real-time AI events", True),
                ("Read event streams",         True),
                ("List topics",                True),
                ("Publish events",             False),
            ],
            "activity": [
                ("Apr 7 · 18:44 UTC", "Consumer group disconnected — cert error",     "Error"),
                ("Apr 7 · 00:00 UTC", "Broker TLS cert renewed — reconnect required", "Error"),
                ("Apr 6 · 22:00 UTC", "Last successful consumer group event",         "Success"),
            ],
            "workflows": {
                "playbooks": [], "alerts": ["Kafka Consumer Down"],
                "policies": [], "cases": [],
            },
            "credentials": [{"type": "service_account_json", "name": "Service account cert"}],
        },

        # ── Tavily ──
        {
            "external_id": "int-016", "name": "Tavily", "abbrev": "Tv",
            "category": "AI Providers", "status": "Healthy", "auth_method": "API Key",
            "owner": "raj.patel", "owner_display": "Raj Patel",
            "environment": "Production", "enabled": True,
            "description": "Tavily web-search API used by research agents for real-time retrieval augmentation. API key is configurable from the Configure modal.",
            "vendor": "Tavily",
            "tags": ["tavily", "web-search", "rag"],
            "config": {},
            "connection": {
                "last_sync": "just now", "last_sync_full": None,
                "last_failed_sync": None, "avg_latency": "280ms", "uptime": "99.90%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "Never (static key)",
                "scopes": ["search:web", "search:news"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Web search for agents",   True),
                ("News search",             True),
                ("Fetch full-page content", True),
                ("Image search",            False),
            ],
            "activity": [
                ("Apr 8 · 14:30 UTC", "API key validated",       "Success"),
                ("Apr 7 · 14:30 UTC", "Daily health check passed","Success"),
            ],
            "workflows": {
                "playbooks": [], "alerts": [], "policies": [], "cases": [],
            },
            "credentials": [{"type": "api_key", "name": "Primary API key",
                             "env_var": "TAVILY_API_KEY"}],
        },

        # ── Ollama (local LLM backend) ──
        {
            "external_id": "int-017", "name": "Ollama", "abbrev": "Ol",
            "category": "AI Providers", "status": "Healthy", "auth_method": "Service Account",
            "owner": "raj.patel", "owner_display": "Raj Patel",
            "environment": "Production", "enabled": True,
            "description": "Self-hosted LLM backend serving llama3.2 via an OpenAI-compatible endpoint. Used by the guard-model service (prompt/output guard) and threat-hunting-agent. No auth — network-isolated to host.docker.internal.",
            "vendor": "Ollama (local)",
            "tags": ["ollama", "llama3.2", "local-llm", "guard", "hunt"],
            "config": {
                "base_url":          _envget("GROQ_BASE_URL")     or "http://host.docker.internal:11434/v1",
                "model":             _envget("LLM_MODEL")         or "llama3.2",
                "guard_prompt_mode": _envget("GUARD_PROMPT_MODE") or "json",
                "keep_alive":        _envget("OLLAMA_KEEP_ALIVE") or "24h",
                "consumers": {
                    "base_url":          ["guard-model", "threat-hunting-agent"],
                    "model":             ["guard-model (GUARD_GROQ_MODEL)", "threat-hunting-agent (HUNT_MODEL)"],
                    "guard_prompt_mode": ["guard-model"],
                    "keep_alive":        ["host Ollama process"],
                },
            },
            "connection": {
                "last_sync": "just now", "last_sync_full": None,
                "last_failed_sync": None, "avg_latency": "850ms", "uptime": "99.70%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "None (network-isolated)",
                "scopes": ["chat:completions", "models:list"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Guard-model prompt screening",   True),
                ("Output-guard semantic scan",     True),
                ("Threat-hunting agent inference", True),
                ("Embeddings",                     False),
                ("Streaming responses",            True),
            ],
            "activity": [
                ("Apr 8 · 14:30 UTC", "Health check passed",                 "Success"),
                ("Apr 8 · 09:00 UTC", "Model warm — keep_alive=24h honored", "Success"),
                ("Apr 7 · 14:30 UTC", "Health check passed",                 "Success"),
            ],
            "workflows": {
                "playbooks": [], "alerts": [],
                "policies":  ["Prompt-Guard v3", "Output-Guard v2"],
                "cases":     [],
            },
            "credentials": [],
        },

        # ── Garak (LLM red-team runner) ──
        {
            "external_id": "int-018", "name": "Garak", "abbrev": "Gk",
            "category": "Security / SIEM", "status": "Healthy", "auth_method": "Service Account",
            "owner": "sarah.chen", "owner_display": "Sarah Chen",
            "environment": "Production", "enabled": True,
            "description": "NVIDIA Garak LLM red-teaming harness. Runs scheduled probe suites (prompt injection, data leakage, jailbreaks) against registered models and reports findings back to the api via a shared-secret-authenticated internal endpoint. Also stores the SPM internal bootstrap secret used by sibling containers to authenticate config hydration from the spm-db at startup.",
            "vendor": "NVIDIA (open source)",
            "tags": ["garak", "red-team", "adversarial", "llm-security"],
            "config": {
                "cpm_api_url": "http://api:8000",
                "internal_endpoint": "/internal/garak/results",
                "probe_suites": ["dan", "promptinject", "leak_replay", "lmrc"],
            },
            "connection": {
                "last_sync": "3h ago", "last_sync_full": "Apr 8 · 11:30 UTC",
                "last_failed_sync": None, "avg_latency": None, "uptime": "99.50%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "Static shared secret",
                "scopes": ["red-team:submit-findings", "red-team:trigger-probe"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Run prompt-injection probes", True),
                ("Run jailbreak probes",        True),
                ("Run data-leakage probes",     True),
                ("Submit findings to api",      True),
                ("Produce compliance evidence", True),
            ],
            "activity": [
                ("Apr 8 · 11:30 UTC", "Daily red-team suite completed — 0 new findings", "Success"),
                ("Apr 7 · 11:30 UTC", "Daily red-team suite completed — 2 new findings", "Warning"),
                ("Apr 6 · 11:30 UTC", "Internal bootstrap secret co-located",            "Info"),
                ("Apr 6 · 11:29 UTC", "Internal shared secret rotated by sarah.chen",    "Info"),
            ],
            "workflows": {
                "playbooks": ["Red-Team Finding Triage"],
                "alerts":    ["Garak New Finding"],
                "policies":  [], "cases": [],
            },
            "credentials": [
                {
                    "type": "shared_secret", "name": "Internal shared secret",
                    "env_var": "GARAK_INTERNAL_SECRET",
                },
                {
                    "type": "internal_bootstrap_secret",
                    "name": "SPM internal bootstrap secret",
                    "env_var": "SPM_INTERNAL_BOOTSTRAP_SECRET",
                },
            ],
        },

        # ── Apache Flink (stream processor, downstream of Kafka) ──
        {
            "external_id": "int-019", "name": "Flink", "abbrev": "Fl",
            "category": "Data / Storage", "status": "Disabled", "auth_method": "Service Account",
            "owner": "mike.torres", "owner_display": "Mike Torres",
            "environment": "Production", "enabled": False,
            "description": "Apache Flink stream-processing cluster. Disabled by default — enable after confirming the local JobManager (port 8081) is healthy and the PyFlink CEP job is RUNNING. Update `jobmanager_url` via Configure if you're pointing at a remote cluster.",
            "vendor": "Apache",
            "tags": ["flink", "streaming", "event-processing", "downstream"],
            "config": {
                "jobmanager_url":      "http://flink-jobmanager:8081",
                "bootstrap_servers":   "kafka-broker:9092",
                "parallelism":         4,
                "checkpoint_interval": "60s",
                "state_backend":       "rocksdb",
                "consumers": {
                    "jobmanager_url":    ["ai-event-enricher-job", "detection-join-job"],
                    "bootstrap_servers": ["ai-event-enricher-job"],
                },
            },
            "connection": {
                "last_sync": "4h ago", "last_sync_full": "Apr 8 · 10:30 UTC",
                "last_failed_sync": "Apr 7 · 18:45 UTC",
                "avg_latency": "410ms", "uptime": "94.20%",
                "health_history": ["ok","ok","ok","ok","ok","ok","ok","ok","ok","warn","warn","warn","warn","warn"],
            },
            "auth": {
                "token_expiry": "Service account cert — shared with Kafka",
                "scopes": ["flink:jobs:submit", "flink:jobs:cancel", "flink:metrics:read"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Consume Kafka AI event stream",    False),
                ("Enrich events with threat intel",  True),
                ("Emit to detection pipeline",       True),
                ("Checkpoint state to RocksDB",      True),
                ("Submit / cancel jobs via REST",    True),
            ],
            "activity": [
                ("Apr 8 · 10:30 UTC", "Checkpoint succeeded — job ai-event-enricher healthy",        "Success"),
                ("Apr 7 · 18:45 UTC", "Kafka source connector backing off — upstream cert error",   "Warning"),
                ("Apr 7 · 18:44 UTC", "Consumer lag climbing — Flink source paused",                "Warning"),
                ("Apr 6 · 22:00 UTC", "Last healthy Kafka → Flink event delivery",                  "Success"),
            ],
            "workflows": {
                "playbooks": [],
                "alerts":    ["Flink Source Backoff", "Flink Checkpoint Failing"],
                "policies":  [], "cases": [],
            },
            "credentials": [
                {"type": "service_account_json", "name": "Service account cert"},
            ],
        },

        # ── PostgreSQL (operational DB — meta-integration on the platform's own DB) ──
        {
            "external_id": "int-020", "name": "PostgreSQL", "abbrev": "Pg",
            "category": "Data / Storage", "status": "Healthy", "auth_method": "API Key",
            "owner": "mike.torres", "owner_display": "Mike Torres",
            "environment": "Production", "enabled": True,
            "description": "PostgreSQL database connector. Pre-configured to point at the AI-SPM platform's own metadata DB (spm-db) so the Test button is green out-of-the-box — swap the host/db/credentials for your real application DB in Configure.",
            "vendor": "PostgreSQL Global Development Group",
            "tags": ["postgres", "rdbms", "data"],
            "config": {
                # Docker-compose hostnames — overridable via Configure.
                "host":     "spm-db",
                "port":     5432,
                "database": "spm",
                "sslmode":  "prefer",
                "username": "spm_rw",
            },
            "connection": {
                "last_sync": "just now", "last_sync_full": None,
                "last_failed_sync": None, "avg_latency": "4ms", "uptime": "99.99%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "None (password auth)",
                "scopes": ["db:read", "db:write"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("SELECT 1 liveness", True),
                ("Schema introspection", True),
                ("Row-level read",      True),
                ("Row-level write",     True),
            ],
            "activity": [
                ("Apr 8 · 14:30 UTC", "SELECT 1 responded ok",     "Success"),
                ("Apr 8 · 08:00 UTC", "Daily liveness check",      "Success"),
            ],
            "workflows": {"playbooks": [], "alerts": [], "policies": [], "cases": []},
            "credentials": [
                # Populated by operator in Configure — the local dev DB
                # password is not seeded from env to avoid baking the
                # compose default into rebuilt containers.
                {"type": "password", "name": "Database password"},
            ],
        },

        # ── Redis (cache / pub-sub) ──
        {
            "external_id": "int-021", "name": "Redis", "abbrev": "Rd",
            "category": "Data / Storage", "status": "Healthy", "auth_method": "API Key",
            "owner": "mike.torres", "owner_display": "Mike Torres",
            "environment": "Production", "enabled": True,
            "description": "Redis key-value store. Pre-configured to point at the AI-SPM platform's own Redis so the Test button (PING) is green out-of-the-box — swap for your real cluster in Configure.",
            "vendor": "Redis Ltd.",
            "tags": ["redis", "cache", "pub-sub"],
            "config": {
                "host": "redis",
                "port": 6379,
                "db":   0,
                "tls":  False,
            },
            "connection": {
                "last_sync": "just now", "last_sync_full": None,
                "last_failed_sync": None, "avg_latency": "1ms", "uptime": "99.99%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "None (optional password)",
                "scopes": ["redis:read", "redis:write"],
                "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("PING liveness",     True),
                ("Key read/write",    True),
                ("Pub/Sub",           True),
                ("Cluster discovery", False),
            ],
            "activity": [
                ("Apr 8 · 14:30 UTC", "PING → PONG", "Success"),
                ("Apr 8 · 08:00 UTC", "Daily liveness check", "Success"),
            ],
            "workflows": {"playbooks": [], "alerts": [], "policies": [], "cases": []},
            # Unauthenticated Redis in dev compose — no credential row needed.
            "credentials": [],
        },
        # ── int-022 — meta-integration that tells spm-llm-proxy which
        # upstream LLM to route agent runtime calls through. The
        # ``default_llm_integration_id`` config key holds the UUID of
        # whichever AI Provider row (OpenAI, Anthropic, Ollama, …) the
        # operator picks. Bootstrap leaves the value alone if already
        # populated; resets to int-017 (Ollama) if missing.
        {
            "external_id": "int-022",
            "name": "AI-SPM Agent Runtime Control Plane (MCP)",
            "abbrev": "AR",
            "category": "AI Providers",
            "status": "Healthy",
            "auth_method": "Service Account",
            "owner": "platform-ops", "owner_display": "Platform Ops",
            "environment": "Production",
            "enabled": True,
            "description": (
                "Routes agent-runtime LLM calls through the configured "
                "upstream provider. Pick which provider in Configure → "
                "default_llm_integration_id."
            ),
            "vendor": "AISPM",
            "tags": ["agent-runtime", "mcp", "internal"],
            # The proxy looks up an integration with
            # connector_type='agent-runtime' and reads
            # config.default_llm_integration_id from it.
            "connector_type": "agent-runtime",
            "config": {
                # Default points at Ollama (int-017). The bootstrap
                # _envget helper will preserve any value already set
                # in the DB — so changing the provider via UI sticks
                # across spm-api restarts.
                "default_llm_integration_id_external": "int-017",
            },
            "connection": {
                "last_sync": "just now", "last_sync_full": None,
                "last_failed_sync": None, "avg_latency": "—", "uptime": "100%",
                "health_history": ["ok"] * 14,
            },
            "auth": {
                "token_expiry": "n/a (in-cluster service account)",
                "scopes": [], "missing_scopes": [], "setup_progress": None,
            },
            "coverage": [
                ("Agent → spm-llm-proxy",  True),
                ("Provider resolution",    True),
            ],
            "activity": [],
            "workflows": {"playbooks": [], "alerts": [], "policies": [], "cases": []},
            "credentials": [],
        },
    ]

    # Normalize pass — inject connector_type based on name, unless the seed
    # dict already set one explicitly.  Kept at the bottom so adding a new
    # row only requires editing the dict, not also a lookup table.
    for r in rows:
        if r.get("connector_type"):
            continue
        nm = (r.get("name") or "").strip().lower()
        ct = _NAME_TO_CONNECTOR_TYPE.get(nm)
        if ct:
            r["connector_type"] = ct
    return rows
