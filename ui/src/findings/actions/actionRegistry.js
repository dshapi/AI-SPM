/**
 * actionRegistry.js
 * ──────────────────
 * Maps finding source/type strings → ordered action descriptors.
 *
 * Each action:
 *   id           — unique stable identifier (used for data-testid)
 *   label        — button text shown to the user
 *   primary      — (optional) marks the hero/CTA action
 *   action       — key into createHandlers() in actionHandlers.js
 *   disabledWhen — (optional) predicate (finding) => bool; disables if true
 *
 * Adding a new finding type: add a new key here and wire the handler in
 * actionHandlers.js if needed. No component code needs to change.
 */

// ── Registry ──────────────────────────────────────────────────────────────────

export const ACTION_REGISTRY = {
  network_exposure: [
    {
      id:      'investigate_network',
      label:   'Investigate Network Exposure',
      primary: true,
      action:  'openLineage',
    },
    {
      id:            'view_port_activity',
      label:         'View Port Activity',
      action:        'openRuntimeByPort',
      disabledWhen:  (f) => !f.id,
    },
    {
      id:            'identify_service',
      label:         'Identify Service Owner',
      action:        'openInventoryByAsset',
      disabledWhen:  (f) => !f.asset?.name,
    },
  ],

  // Alias used by the threat-hunting proc-network scanner
  unexpected_listen_ports: [
    {
      id:      'investigate_network',
      label:   'Investigate Network Exposure',
      primary: true,
      action:  'openLineage',
    },
    {
      id:           'view_port_activity',
      label:        'View Port Activity',
      action:       'openRuntimeByPort',
      disabledWhen: (f) => !f.id,
    },
    {
      id:           'identify_service',
      label:        'Identify Service Owner',
      action:       'openInventoryByAsset',
      disabledWhen: (f) => !f.asset?.name,
    },
  ],

  prompt_injection: [
    {
      id:      'inspect_prompt',
      label:   'Inspect Prompt Flow',
      primary: true,
      action:  'openLineage',
    },
    {
      id:           'view_session',
      label:        'View Conversation Trace',
      action:       'openRuntimeSession',
      disabledWhen: (f) => !f.id,
    },
  ],

  secrets_exposure: [
    {
      id:      'revoke_secret',
      label:   'Revoke Credential',
      primary: true,
      action:  'revokeSecret',
    },
    {
      id:     'locate_source',
      label:  'Locate Source',
      action: 'openLineage',
    },
  ],

  prompt_secret_exfiltration: [
    {
      id:      'inspect_prompt',
      label:   'Inspect Prompt Flow',
      primary: true,
      action:  'openLineage',
    },
    {
      id:     'revoke_secret',
      label:  'Revoke Credential',
      action: 'revokeSecret',
    },
  ],

  tool_misuse: [
    {
      id:           'inspect_tools',
      label:        'Inspect Tool Calls',
      primary:      true,
      action:       'openRuntimeSession',
      disabledWhen: (f) => !f.id,
    },
    {
      id:     'review_permissions',
      label:  'Review Permissions',
      action: 'openPolicy',
    },
  ],

  tool_misuse_detection: [
    {
      id:           'inspect_tools',
      label:        'Inspect Tool Calls',
      primary:      true,
      action:       'openRuntimeSession',
      disabledWhen: (f) => !f.id,
    },
    {
      id:     'review_permissions',
      label:  'Review Permissions',
      action: 'openPolicy',
    },
  ],

  runtime_anomaly: [
    {
      id:           'analyze_behavior',
      label:        'Analyze Behavior',
      primary:      true,
      action:       'openRuntimeSession',
      disabledWhen: (f) => !f.id,
    },
  ],

  data_leakage_detection: [
    {
      id:      'inspect_data_flow',
      label:   'Inspect Data Flow',
      primary: true,
      action:  'openLineage',
    },
    {
      id:           'view_session',
      label:        'View Session',
      action:       'openRuntimeSession',
      disabledWhen: (f) => !f.id,
    },
  ],

  // Generic threat-hunt findings (used by the hunt engine source tag)
  threat_hunt: [
    {
      id:           'view_session',
      label:        'View Session Trace',
      primary:      true,
      action:       'openRuntimeSession',
      disabledWhen: (f) => !f.id,
    },
  ],

  'threat-hunting-agent': [
    {
      id:           'view_session',
      label:        'View Session Trace',
      primary:      true,
      action:       'openRuntimeSession',
      disabledWhen: (f) => !f.id,
    },
  ],
}

// ── Public helpers ─────────────────────────────────────────────────────────────

/**
 * Returns the action list for a finding's source/type string.
 * Normalises to lowercase; falls back to empty array for unknown types
 * so the UI degrades gracefully.
 */
export function getActionsForFinding(finding) {
  const key = (finding.source ?? '').toLowerCase()
  return ACTION_REGISTRY[key] ?? []
}
