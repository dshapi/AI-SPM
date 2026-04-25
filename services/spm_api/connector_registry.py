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
    # `enum_integration` renders as a dropdown of currently-active integration
    # rows matching `options_provider`. Used by connector types that reference
    # other integrations (e.g. agent-runtime → default LLM, Tavily). The
    # frontend resolves the `options_provider` string to a query against
    # `GET /api/spm/integrations?category=...&vendor=...` (see the
    # `_OPTIONS_PROVIDER_FILTERS` mapping below).
    "enum_integration",
    # `float` is used by resource-quota fields (CPU quota etc.) where the
    # canonical value is a fractional number that the frontend renders as a
    # number input with step="0.1".
    "float",
]

FieldGroup = Literal[
    "Connection", "Credentials", "Advanced",
    # Groups used by the agent-runtime ConnectorType:
    "Defaults", "Resources", "Tool behaviour", "Audit",
]


# Mapping from `FieldSpec.options_provider` strings to the
# (category, vendor) filter pair the frontend should pass to
# `GET /api/spm/integrations`. Single source of truth — both the
# Phase 3 SchemaForm dropdown and the Phase 1 backend tests reference
# this dict so adding a new provider category is a one-line change.
_OPTIONS_PROVIDER_FILTERS: Dict[str, Tuple[Optional[str], Optional[str]]] = {
    "ai_provider_integrations": ("AI Providers", None),
    "tavily_integrations":      ("AI Providers", "Tavily"),
}


def options_provider_filters(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve an options_provider name to (category, vendor) filter values.

    Returns (None, None) for unknown names so callers can choose to
    surface that as an error or fall back to "list all integrations".
    """
    return _OPTIONS_PROVIDER_FILTERS.get(name, (None, None))


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
    # Only for type="enum_integration": names a filter recipe in
    # `_OPTIONS_PROVIDER_FILTERS`. Common values:
    #   - "ai_provider_integrations" → all active AI Provider integrations
    #   - "tavily_integrations"       → only Tavily integrations
    options_provider: str


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
    probe_agent_runtime,
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
            # The dev stack ships a real Flink JobManager at
            # http://flink-jobmanager:8081 (see docker-compose.yml). The
            # default below probes that. Override jobmanager_url to point
            # at a remote/production cluster.
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

    # ══════════════════════════════════════════════════════════════════════════
    # Agent Runtime Control Plane (1) — internal vendor
    # ══════════════════════════════════════════════════════════════════════════

    "agent-runtime": {
        "key": "agent-runtime",
        "label": "AI-SPM Agent Runtime Control Plane (MCP)",
        "category": "AI Providers",
        "vendor": "AI-SPM",
        "icon_hint": "bot",
        "description": (
            "Hosts customer-uploaded AI agents in sandboxed containers. "
            "Provides MCP tools (web_fetch) and an OpenAI-compatible LLM proxy. "
            "Configure the default LLM and Tavily integration here."
        ),
        "fields": [
            # ── Defaults ──────────────────────────────────────────────────────
            {"key": "default_llm_integration_id",
             "label": "Default LLM",
             "type": "enum_integration",
             "required": True, "group": "Defaults",
             "hint": "Active AI Provider integration that backs spm-llm-proxy.",
             "options_provider": "ai_provider_integrations"},
            {"key": "tavily_integration_id",
             "label": "Tavily Integration",
             "type": "enum_integration",
             "required": True, "group": "Defaults",
             "options_provider": "tavily_integrations"},
            {"key": "default_model_name",
             "label": "Default model name",
             "type": "string", "default": "llama3.1:8b",
             "group": "Defaults"},
            # ── Resources ─────────────────────────────────────────────────────
            {"key": "default_memory_mb",
             "label": "Memory per agent (MB)",
             "type": "integer", "default": 512, "group": "Resources"},
            {"key": "default_cpu_quota",
             "label": "CPU quota",
             "type": "float", "default": 0.5, "group": "Resources"},
            {"key": "tool_call_timeout_s",
             "label": "Tool call timeout (s)",
             "type": "integer", "default": 30, "group": "Resources"},
            {"key": "max_concurrent_agents",
             "label": "Max concurrent agents",
             "type": "integer", "default": 50, "group": "Resources"},
            {"key": "max_sessions_per_agent",
             "label": "Max chat sessions per agent",
             "type": "integer", "default": 100, "group": "Resources"},
            # ── Tool behaviour ────────────────────────────────────────────────
            {"key": "tavily_max_results",
             "label": "Tavily max results",
             "type": "integer", "default": 5, "group": "Tool behaviour"},
            {"key": "tavily_max_chars",
             "label": "Tavily max chars per result",
             "type": "integer", "default": 4000, "group": "Tool behaviour"},
            # ── Audit ─────────────────────────────────────────────────────────
            {"key": "log_llm_prompts",
             "label": "Log LLM prompts",
             "type": "boolean", "default": True, "group": "Audit"},
            {"key": "audit_topic_suffix",
             "label": "Audit topic suffix",
             "type": "string", "default": "audit_events", "group": "Audit"},
        ],
        "probe": probe_agent_runtime,
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


# ─── Cross-integration probe helper ─────────────────────────────────────────
#
# Used by ConnectorTypes whose "Test Connection" depends on another
# integration being healthy (today: ``agent-runtime`` checks the
# referenced default LLM and Tavily integrations). Loads the integration
# row by primary-key id, decodes its declared secrets, and dispatches to
# the registry-declared probe.

async def probe_integration_by_id(
    integration_id: str,
) -> Tuple[bool, str, Optional[int]]:
    """Run the registered probe for an integration row, by ID.

    Returns ``(False, "...", None)`` if the row does not exist or its
    connector_type is unknown — never raises so the caller can surface a
    clean error to the operator.

    Imports DB access lazily so the registry module remains importable
    in environments without a database (unit tests, doc generators).
    """
    if not integration_id:
        return False, "integration_id missing", None

    try:
        from spm.db.session import get_session_factory  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover — DB always present in deploys
        return False, "spm.db.session not importable", None

    from sqlalchemy import select          # type: ignore
    from sqlalchemy.orm import selectinload  # type: ignore

    # Local import — avoids a circular at module-import time since
    # spm.db.models pulls in platform_shared.models which can in turn
    # import this module under unusual import orderings.
    from spm.db.models import Integration  # type: ignore

    # Decode-secret helper lives in integrations_routes; import lazily.
    try:
        from integrations_routes import _decode_secret  # type: ignore
    except ModuleNotFoundError:
        from services.spm_api.integrations_routes import _decode_secret  # type: ignore

    sf = get_session_factory()
    async with sf() as db:
        stmt = (
            select(Integration)
            .where(Integration.id == integration_id)
            .options(selectinload(Integration.credentials))
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return False, f"integration {integration_id!r} not found", None

        ct = get_connector(getattr(row, "connector_type", None))
        if ct is None:
            return False, (
                f"integration {integration_id!r} has unknown "
                f"connector_type {getattr(row, 'connector_type', None)!r}"
            ), None

        cfg = dict(row.config or {})
        creds: Dict[str, Any] = {}
        for f in ct["fields"]:
            if not f.get("secret"):
                continue
            key = f["key"]
            c = next(
                (c for c in (row.credentials or [])
                 if c.credential_type == key and c.is_configured),
                None,
            )
            if c:
                creds[key] = _decode_secret(c.value_enc)

        try:
            return await ct["probe"](cfg, creds)
        except Exception as e:  # noqa: BLE001 — never raise from a probe
            return False, f"probe for {ct['key']!r} errored: {e}", None
