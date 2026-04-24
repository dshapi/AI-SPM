"""
Connector registry — single source of truth for every integration type the
AI-SPM platform knows how to talk to.

Why this exists
───────────────
Before this module, the Configure modal rendered one of three hand-coded
forms (`ai_provider` / `basic_auth` / `cert`) picked by a fragile
credential-type / category chain, and the probe dispatcher was a big
`if name == "anthropic"` chain.  Neither approach could answer "what does
Postgres need?" — because the fields Postgres wants (host, port, db,
user, password, sslmode) are specific to Postgres and there was no place
to say so.

This file IS the answer.  Every integration type declares its connection
schema + a probe function, the frontend renders whichever fields the
vendor declared, and the backend dispatches Test clicks by looking up the
vendor's probe.  Adding a new vendor = one dict entry + one probe fn.

Concrete shape
──────────────
    CONNECTOR_TYPES: Dict[str, ConnectorType]

Each ``ConnectorType`` has:
  * ``key`` — stable URL-safe identifier ("postgres", "kafka"); stored on
    the integrations table, referenced by the UI, used to dispatch probes
  * ``label`` — human-readable display name ("PostgreSQL")
  * ``category`` — one of the six existing Integrations-page categories
  * ``vendor`` — vendor/company name, surfaced in UI metadata
  * ``icon_hint`` — optional lucide-react icon hint (purely cosmetic)
  * ``description`` — one-line blurb shown in the vendor catalog picker
  * ``fields`` — ordered list of FieldSpec (see below), drives both the
    Add Integration form and the Configure modal via <SchemaForm>
  * ``probe`` — async callable ``(config, credentials) -> (ok, msg, latency_ms)``
    that actually hits the vendor to confirm liveness

FieldSpec rules (critical)
──────────────────────────
  * ``key`` MUST be unique within a connector's field list
  * ``secret=True`` fields go to ``integration_credentials`` (encrypted);
    everything else goes to ``integrations.config`` (plaintext JSON)
  * ``type`` drives the UI widget:
        "string"   -> <input type=text>
        "integer"  -> <input type=number step=1>
        "password" -> <input type=password> (implies secret=True)
        "enum"     -> <select> (requires ``options``)
        "textarea" -> <textarea rows=6> (for PEM certs, multi-line JSON)
        "boolean"  -> <input type=checkbox>
        "url"      -> <input type=url>
  * ``group`` sorts fields into collapsible sections in the UI.  Use
    "Connection" for host/port/URL, "Credentials" for keys/passwords,
    "Advanced" for things the user almost never needs to touch.
  * ``required`` — UI shows a red asterisk; backend enforces on submit
  * ``default`` — pre-filled at form open.  Used heavily for the
    docker-compose-aligned defaults on Kafka/Redis/Postgres so the Test
    button succeeds out of the box in this specific dev stack.

This registry is intentionally Python-only (not DB-backed, not YAML) —
see docs/superpowers/specs for the design discussion.  Adding a new
connector-type at runtime is not a feature; ship a PR.
"""
from __future__ import annotations

from typing import (
    Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple, TypedDict,
)

# ─── Type definitions ───────────────────────────────────────────────────────────

FieldType = Literal[
    "string", "integer", "password", "enum", "textarea", "boolean", "url",
]

FieldGroup = Literal["Connection", "Credentials", "Advanced"]


class FieldSpec(TypedDict, total=False):
    # Required keys
    key:         str
    label:       str
    type:        FieldType
    # Optional keys
    required:    bool
    secret:      bool
    default:     Any
    placeholder: str
    options:     List[str]   # only for type="enum"
    hint:        str
    group:       FieldGroup


# Probe signature: receives the resolved config dict and a credentials dict
# (decrypted, keyed by field.key).  Never raises — catches network errors
# and returns (ok=False, msg=...) so the HTTP route can always respond.
ProbeFn = Callable[
    [Dict[str, Any], Dict[str, Any]],
    Awaitable[Tuple[bool, str, Optional[int]]],
]


class ConnectorType(TypedDict, total=False):
    # Required keys
    key:         str
    label:       str
    category:    str
    fields:      List[FieldSpec]
    probe:       ProbeFn
    # Optional keys
    vendor:      str
    icon_hint:   str
    description: str


# Import probe implementations here at module load.  Kept in a sibling
# file so this registry is pure data and easy to scan at a glance.  If
# you're adding a new connector-type, write your probe in
# connector_probes.py first, then reference it from the dict below.
from connector_probes import (  # noqa: E402  (after-docstring import is deliberate)
    probe_anthropic,
    probe_azure_openai,
    probe_bedrock_stub,
    probe_confluence,
    probe_entra_stub,
    probe_flink,
    probe_garak_stub,
    probe_jira,
    probe_kafka,
    probe_mssentinel_stub,
    probe_ollama,
    probe_okta,
    probe_openai_compatible,
    probe_postgres,
    probe_redis,
    probe_s3_stub,
    probe_servicenow,
    probe_slack,
    probe_splunk,
    probe_tavily,
    probe_vertex_stub,
)


# ─── Registry ───────────────────────────────────────────────────────────────────

CONNECTOR_TYPES: Dict[str, ConnectorType] = {

    # ══════════════════════════════════════════════════════════════════════════
    # AI Providers (7)
    # ══════════════════════════════════════════════════════════════════════════

    "openai": {
        "key": "openai", "label": "OpenAI", "category": "AI Providers",
        "vendor": "OpenAI", "icon_hint": "brain",
        "description": "OpenAI chat + embeddings API. Probes GET /v1/models.",
        "fields": [
            {"key": "base_url", "label": "Base URL", "type": "url",
             "group": "Connection", "required": False,
             "default": "https://api.openai.com/v1",
             "hint": "Override only for OpenAI-compatible gateways (Azure AI Studio proxy, LiteLLM, etc.)."},
            {"key": "model", "label": "Default Model", "type": "string",
             "group": "Connection", "required": False,
             "placeholder": "gpt-4o-mini", "default": "gpt-4o-mini"},
            {"key": "api_key", "label": "API Key", "type": "password",
             "group": "Credentials", "required": True, "secret": True,
             "placeholder": "sk-…"},
        ],
        "probe": probe_openai_compatible,
    },

    "azure_openai": {
        "key": "azure_openai", "label": "Azure OpenAI", "category": "AI Providers",
        "vendor": "Microsoft", "icon_hint": "cloud",
        "description": "Azure-hosted OpenAI deployments. Tier-2 stub probe — credentials-present check.",
        "fields": [
            {"key": "endpoint", "label": "Endpoint", "type": "url",
             "group": "Connection", "required": True,
             "placeholder": "https://my-resource.openai.azure.com"},
            {"key": "deployment", "label": "Deployment Name", "type": "string",
             "group": "Connection", "required": True,
             "placeholder": "gpt-4o-mini-prod"},
            {"key": "api_version", "label": "API Version", "type": "string",
             "group": "Connection", "required": False,
             "default": "2024-10-21",
             "hint": "Azure OpenAI date-based API version."},
            {"key": "api_key", "label": "API Key", "type": "password",
             "group": "Credentials", "required": True, "secret": True},
        ],
        "probe": probe_azure_openai,
    },

    "anthropic": {
        "key": "anthropic", "label": "Anthropic", "category": "AI Providers",
        "vendor": "Anthropic", "icon_hint": "sparkles",
        "description": "Claude chat models. Probes GET /v1/models with x-api-key.",
        "fields": [
            {"key": "base_url", "label": "Base URL", "type": "url",
             "group": "Connection", "required": False,
             "default": "https://api.anthropic.com"},
            {"key": "model", "label": "Default Model", "type": "string",
             "group": "Connection", "required": False,
             "placeholder": "claude-sonnet-4-6",
             "default": "claude-sonnet-4-6"},
            {"key": "api_key", "label": "API Key", "type": "password",
             "group": "Credentials", "required": True, "secret": True,
             "placeholder": "sk-ant-…"},
        ],
        "probe": probe_anthropic,
    },

    "bedrock": {
        "key": "bedrock", "label": "Amazon Bedrock", "category": "AI Providers",
        "vendor": "Amazon Web Services", "icon_hint": "aws",
        "description": "Bedrock foundation models via IAM. Tier-2 stub probe.",
        "fields": [
            {"key": "region", "label": "AWS Region", "type": "string",
             "group": "Connection", "required": True,
             "placeholder": "us-east-1", "default": "us-east-1"},
            {"key": "role_arn", "label": "Role ARN", "type": "string",
             "group": "Credentials", "required": True,
             "placeholder": "arn:aws:iam::123456789012:role/BedrockInvoke",
             "hint": "IAM role the spm-api assumes via STS. Trust policy must allow this service's task role."},
            {"key": "external_id", "label": "External ID", "type": "password",
             "group": "Credentials", "required": False, "secret": True,
             "hint": "Optional — if the role's trust policy requires an external ID."},
        ],
        "probe": probe_bedrock_stub,
    },

    "vertex": {
        "key": "vertex", "label": "Google Vertex AI", "category": "AI Providers",
        "vendor": "Google Cloud", "icon_hint": "cloud",
        "description": "Vertex AI Gemini / Claude-on-Vertex. Tier-2 stub probe.",
        "fields": [
            {"key": "project_id", "label": "GCP Project ID", "type": "string",
             "group": "Connection", "required": True,
             "placeholder": "my-gcp-project"},
            {"key": "location", "label": "Location", "type": "string",
             "group": "Connection", "required": True,
             "default": "us-central1"},
            {"key": "model", "label": "Default Model", "type": "string",
             "group": "Connection", "required": False,
             "placeholder": "gemini-1.5-pro"},
            {"key": "service_account_json", "label": "Service Account JSON",
             "type": "textarea", "group": "Credentials",
             "required": True, "secret": True,
             "hint": "Paste the full JSON key file content."},
        ],
        "probe": probe_vertex_stub,
    },

    "tavily": {
        "key": "tavily", "label": "Tavily", "category": "AI Providers",
        "vendor": "Tavily", "icon_hint": "search",
        "description": "Tavily web-search API used by research agents.",
        "fields": [
            {"key": "api_key", "label": "API Key", "type": "password",
             "group": "Credentials", "required": True, "secret": True,
             "placeholder": "tvly-…"},
        ],
        "probe": probe_tavily,
    },

    "ollama": {
        "key": "ollama", "label": "Ollama", "category": "AI Providers",
        "vendor": "Ollama (self-hosted)", "icon_hint": "server",
        "description": "Self-hosted LLM backend. Probes GET /api/tags.",
        "fields": [
            {"key": "base_url", "label": "Base URL", "type": "url",
             "group": "Connection", "required": True,
             "default": "http://host.docker.internal:11434/v1",
             "hint": "OpenAI-compatible surface. /v1 is stripped automatically when probing the native /api/tags endpoint."},
            {"key": "model", "label": "Default Model", "type": "string",
             "group": "Connection", "required": False,
             "placeholder": "llama3.2", "default": "llama3.2"},
            {"key": "keep_alive", "label": "Keep-Alive", "type": "string",
             "group": "Advanced", "required": False,
             "default": "24h",
             "hint": "How long Ollama keeps models warm between calls."},
        ],
        "probe": probe_ollama,
    },

    # ══════════════════════════════════════════════════════════════════════════
    # Security / SIEM (3)
    # ══════════════════════════════════════════════════════════════════════════

    "splunk": {
        "key": "splunk", "label": "Splunk", "category": "Security / SIEM",
        "vendor": "Splunk Inc.", "icon_hint": "activity",
        "description": "Splunk HEC. Probes GET /services/collector/health with token.",
        "fields": [
            {"key": "hec_url", "label": "HEC URL", "type": "url",
             "group": "Connection", "required": True,
             "placeholder": "https://splunk.example.com:8088"},
            {"key": "verify_tls", "label": "Verify TLS", "type": "boolean",
             "group": "Advanced", "required": False, "default": True,
             "hint": "Uncheck for self-signed dev clusters."},
            {"key": "hec_token", "label": "HEC Token", "type": "password",
             "group": "Credentials", "required": True, "secret": True},
        ],
        "probe": probe_splunk,
    },

    "sentinel": {
        "key": "sentinel", "label": "Microsoft Sentinel", "category": "Security / SIEM",
        "vendor": "Microsoft", "icon_hint": "shield",
        "description": "Sentinel via Log Analytics API. Tier-2 stub probe.",
        "fields": [
            {"key": "workspace_id", "label": "Workspace ID", "type": "string",
             "group": "Connection", "required": True},
            {"key": "tenant_id", "label": "Tenant ID", "type": "string",
             "group": "Credentials", "required": True},
            {"key": "client_id", "label": "Client ID", "type": "string",
             "group": "Credentials", "required": True},
            {"key": "client_secret", "label": "Client Secret", "type": "password",
             "group": "Credentials", "required": True, "secret": True},
        ],
        "probe": probe_mssentinel_stub,
    },

    "garak": {
        "key": "garak", "label": "Garak", "category": "Security / SIEM",
        "vendor": "NVIDIA (open source)", "icon_hint": "bug",
        "description": "LLM red-team runner (internal). Probe checks shared-secret presence.",
        "fields": [
            {"key": "cpm_api_url", "label": "CPM API URL", "type": "url",
             "group": "Connection", "required": True,
             "default": "http://api:8000"},
            {"key": "shared_secret", "label": "Shared Secret", "type": "password",
             "group": "Credentials", "required": True, "secret": True},
        ],
        "probe": probe_garak_stub,
    },

    # ══════════════════════════════════════════════════════════════════════════
    # Ticketing / Workflow (2)
    # ══════════════════════════════════════════════════════════════════════════

    "jira": {
        "key": "jira", "label": "Jira", "category": "Ticketing / Workflow",
        "vendor": "Atlassian", "icon_hint": "clipboard",
        "description": "Jira Cloud / Server. Probes GET /rest/api/3/myself.",
        "fields": [
            {"key": "base_url", "label": "Base URL", "type": "url",
             "group": "Connection", "required": True,
             "placeholder": "https://acme.atlassian.net"},
            {"key": "email", "label": "Account Email", "type": "string",
             "group": "Credentials", "required": True,
             "placeholder": "svc-spm@acme.com"},
            {"key": "api_token", "label": "API Token", "type": "password",
             "group": "Credentials", "required": True, "secret": True,
             "hint": "From id.atlassian.com → Security → API tokens."},
        ],
        "probe": probe_jira,
    },

    "servicenow": {
        "key": "servicenow", "label": "ServiceNow", "category": "Ticketing / Workflow",
        "vendor": "ServiceNow", "icon_hint": "git-pull-request",
        "description": "ServiceNow Table API. Probes GET /api/now/table/sys_user?sysparm_limit=1.",
        "fields": [
            {"key": "instance_url", "label": "Instance URL", "type": "url",
             "group": "Connection", "required": True,
             "placeholder": "https://acme.service-now.com"},
            {"key": "username", "label": "Username", "type": "string",
             "group": "Credentials", "required": True},
            {"key": "password", "label": "Password", "type": "password",
             "group": "Credentials", "required": True, "secret": True},
        ],
        "probe": probe_servicenow,
    },

    # ══════════════════════════════════════════════════════════════════════════
    # Messaging / Collab (1)
    # ══════════════════════════════════════════════════════════════════════════

    "slack": {
        "key": "slack", "label": "Slack", "category": "Messaging / Collab",
        "vendor": "Salesforce / Slack", "icon_hint": "message-circle",
        "description": "Slack bot integration. Probes GET auth.test.",
        "fields": [
            {"key": "default_channel", "label": "Default Channel", "type": "string",
             "group": "Connection", "required": False,
             "placeholder": "#spm-alerts"},
            {"key": "bot_token", "label": "Bot Token", "type": "password",
             "group": "Credentials", "required": True, "secret": True,
             "placeholder": "xoxb-…",
             "hint": "Requires scopes: chat:write, channels:read."},
        ],
        "probe": probe_slack,
    },

    # ══════════════════════════════════════════════════════════════════════════
    # Identity / Access (2)
    # ══════════════════════════════════════════════════════════════════════════

    "okta": {
        "key": "okta", "label": "Okta", "category": "Identity / Access",
        "vendor": "Okta", "icon_hint": "user-check",
        "description": "Okta directory API. Probes GET /api/v1/users?limit=1.",
        "fields": [
            {"key": "org_url", "label": "Org URL", "type": "url",
             "group": "Connection", "required": True,
             "placeholder": "https://acme.okta.com"},
            {"key": "api_token", "label": "SSWS API Token", "type": "password",
             "group": "Credentials", "required": True, "secret": True,
             "hint": "Admin → Security → API → Create token."},
        ],
        "probe": probe_okta,
    },

    "entra": {
        "key": "entra", "label": "Entra ID", "category": "Identity / Access",
        "vendor": "Microsoft", "icon_hint": "users",
        "description": "Entra ID (Azure AD). Tier-2 stub probe — credentials-present check.",
        "fields": [
            {"key": "tenant_id", "label": "Tenant ID", "type": "string",
             "group": "Credentials", "required": True},
            {"key": "client_id", "label": "Client ID", "type": "string",
             "group": "Credentials", "required": True},
            {"key": "client_secret", "label": "Client Secret", "type": "password",
             "group": "Credentials", "required": True, "secret": True},
        ],
        "probe": probe_entra_stub,
    },

    # ══════════════════════════════════════════════════════════════════════════
    # Data / Storage (6 — S3, Confluence, Kafka, Flink, Postgres, Redis)
    # ══════════════════════════════════════════════════════════════════════════

    "s3": {
        "key": "s3", "label": "Amazon S3", "category": "Data / Storage",
        "vendor": "Amazon Web Services", "icon_hint": "archive",
        "description": "S3 bucket (logs, artifacts). Tier-2 stub probe.",
        "fields": [
            {"key": "bucket", "label": "Bucket Name", "type": "string",
             "group": "Connection", "required": True,
             "placeholder": "acme-ai-logs"},
            {"key": "region", "label": "AWS Region", "type": "string",
             "group": "Connection", "required": True,
             "default": "us-east-1"},
            {"key": "role_arn", "label": "Role ARN", "type": "string",
             "group": "Credentials", "required": True,
             "placeholder": "arn:aws:iam::123456789012:role/SpmReadS3"},
        ],
        "probe": probe_s3_stub,
    },

    "confluence": {
        "key": "confluence", "label": "Confluence", "category": "Data / Storage",
        "vendor": "Atlassian", "icon_hint": "book-open",
        "description": "Confluence pages (RAG source). Probes GET /wiki/rest/api/space?limit=1.",
        "fields": [
            {"key": "base_url", "label": "Base URL", "type": "url",
             "group": "Connection", "required": True,
             "placeholder": "https://acme.atlassian.net"},
            {"key": "email", "label": "Account Email", "type": "string",
             "group": "Credentials", "required": True},
            {"key": "api_token", "label": "API Token", "type": "password",
             "group": "Credentials", "required": True, "secret": True},
        ],
        "probe": probe_confluence,
    },

    "kafka": {
        "key": "kafka", "label": "Apache Kafka", "category": "Data / Storage",
        "vendor": "Apache Software Foundation", "icon_hint": "zap",
        "description": "Event streaming. Probes TCP connect to the first bootstrap broker.",
        "fields": [
            # Defaults point at the in-compose broker so Test succeeds out
            # of the box. Change to your real brokers in Configure.
            {"key": "bootstrap_servers", "label": "Bootstrap Servers", "type": "string",
             "group": "Connection", "required": True,
             "default": "kafka-broker:9092",
             "placeholder": "broker-1:9092,broker-2:9092",
             "hint": "Comma-separated host:port list. Only the first broker is probed."},
            {"key": "security_protocol", "label": "Security Protocol", "type": "enum",
             "group": "Advanced", "required": False,
             "options": ["PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"],
             "default": "PLAINTEXT"},
            {"key": "service_account_json", "label": "Service Account Certificate",
             "type": "textarea", "group": "Credentials",
             "required": False, "secret": True,
             "hint": "Only required for SASL_SSL / SSL. Leave blank for PLAINTEXT."},
        ],
        "probe": probe_kafka,
    },

    "flink": {
        "key": "flink", "label": "Apache Flink", "category": "Data / Storage",
        "vendor": "Apache Software Foundation", "icon_hint": "activity",
        "description": "Stream processing. Probes GET /overview on the JobManager REST port.",
        "fields": [
            # NOTE: the AI-SPM dev stack runs a custom 'flink-cep' Python
            # consumer, not real Apache Flink, so this probe will fail in
            # the default dev compose. Point it at your real Flink
            # JobManager or ignore — the integration appearance + schema
            # is still correct for customers running real Flink.
            {"key": "jobmanager_url", "label": "JobManager URL", "type": "url",
             "group": "Connection", "required": True,
             "default": "http://flink-jobmanager:8081",
             "placeholder": "http://flink.prod.internal:8081"},
            {"key": "bootstrap_servers", "label": "Kafka Bootstrap Servers", "type": "string",
             "group": "Connection", "required": False,
             "default": "kafka-broker:9092",
             "hint": "Kafka source for Flink jobs. Used in lineage only; not probed."},
            {"key": "parallelism", "label": "Default Parallelism", "type": "integer",
             "group": "Advanced", "required": False, "default": 4},
            {"key": "service_account_json", "label": "Service Account Certificate",
             "type": "textarea", "group": "Credentials",
             "required": False, "secret": True,
             "hint": "Only required for secured Flink REST (Kerberos / mTLS)."},
        ],
        "probe": probe_flink,
    },

    "postgres": {
        "key": "postgres", "label": "PostgreSQL", "category": "Data / Storage",
        "vendor": "PostgreSQL Global Development Group", "icon_hint": "database",
        "description": "PostgreSQL database. Probes SELECT 1 via asyncpg.",
        "fields": [
            # Defaults point at the in-compose spm-db so Test succeeds out
            # of the box — same DB the platform uses for its own metadata.
            {"key": "host", "label": "Host", "type": "string",
             "group": "Connection", "required": True,
             "default": "spm-db", "placeholder": "db.prod.internal"},
            {"key": "port", "label": "Port", "type": "integer",
             "group": "Connection", "required": True, "default": 5432},
            {"key": "database", "label": "Database", "type": "string",
             "group": "Connection", "required": True,
             "default": "spm"},
            {"key": "sslmode", "label": "SSL Mode", "type": "enum",
             "group": "Advanced", "required": False,
             "options": ["disable", "prefer", "require", "verify-ca", "verify-full"],
             "default": "prefer"},
            {"key": "username", "label": "Username", "type": "string",
             "group": "Credentials", "required": True,
             "default": "spm_rw"},
            {"key": "password", "label": "Password", "type": "password",
             "group": "Credentials", "required": True, "secret": True,
             "hint": "Stored encrypted. Leave blank on re-save to keep the existing password."},
        ],
        "probe": probe_postgres,
    },

    "redis": {
        "key": "redis", "label": "Redis", "category": "Data / Storage",
        "vendor": "Redis Ltd.", "icon_hint": "zap",
        "description": "Redis key-value store. Probes PING via redis-py async.",
        "fields": [
            # Defaults point at the in-compose redis service.
            {"key": "host", "label": "Host", "type": "string",
             "group": "Connection", "required": True,
             "default": "redis", "placeholder": "redis.prod.internal"},
            {"key": "port", "label": "Port", "type": "integer",
             "group": "Connection", "required": True, "default": 6379},
            {"key": "db", "label": "Database Number", "type": "integer",
             "group": "Advanced", "required": False, "default": 0,
             "hint": "Redis logical DB index (0–15 typical)."},
            {"key": "tls", "label": "Use TLS", "type": "boolean",
             "group": "Advanced", "required": False, "default": False},
            {"key": "password", "label": "Password", "type": "password",
             "group": "Credentials", "required": False, "secret": True,
             "hint": "Blank for an unauthenticated Redis (common in dev)."},
        ],
        "probe": probe_redis,
    },
}


# ─── Registry helpers ───────────────────────────────────────────────────────────

def list_connector_types() -> List[Dict[str, Any]]:
    """Return a JSON-safe representation of the registry (probe stripped).

    Used by ``GET /integrations/connector-types``.  Sorted by category
    then label so the vendor catalog in the UI has a stable ordering.
    """
    out: List[Dict[str, Any]] = []
    for ct in CONNECTOR_TYPES.values():
        out.append({
            "key":         ct["key"],
            "label":       ct["label"],
            "category":    ct["category"],
            "vendor":      ct.get("vendor"),
            "icon_hint":   ct.get("icon_hint"),
            "description": ct.get("description"),
            "fields":      [dict(f) for f in ct["fields"]],
        })
    out.sort(key=lambda x: (x["category"], x["label"].lower()))
    return out


def get_connector(key: str) -> Optional[ConnectorType]:
    """Registry lookup by ``connector_type`` key.  Case-insensitive for
    operator-friendliness — the UI passes lowercase, but a stored row
    from a manual DB edit might be uppercase."""
    if not key:
        return None
    return CONNECTOR_TYPES.get(key.lower())


def secret_field_keys(key: str) -> List[str]:
    """Return the field.key values for fields with ``secret=True`` on a
    given connector-type.  Used by the Configure route to split the
    submitted payload into (credentials, config)."""
    ct = get_connector(key)
    if not ct:
        return []
    return [f["key"] for f in ct["fields"] if f.get("secret")]


def validate_submission(
    key: str, submission: Dict[str, Any], *, partial: bool = False,
) -> Tuple[bool, str]:
    """Validate a submission against a connector-type schema.

    When ``partial`` is True (Configure modal — "leave blank to keep"),
    required fields are NOT enforced; only unknown keys are rejected and
    declared types are best-effort coerced via simple checks.  The
    non-partial path (Create modal) enforces required.
    """
    ct = get_connector(key)
    if not ct:
        return False, f"unknown connector_type '{key}'"
    allowed = {f["key"] for f in ct["fields"]}
    for k in submission.keys():
        if k not in allowed:
            return False, f"unknown field '{k}' for connector '{key}'"
    if partial:
        return True, "ok"
    for f in ct["fields"]:
        if f.get("required") and not submission.get(f["key"]):
            return False, f"missing required field '{f['key']}'"
    return True, "ok"
