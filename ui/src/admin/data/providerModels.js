/**
 * providerModels.js
 * ──────────────────
 * Static "what does this provider ship?" registry used by the Configure
 * modal to render the Model field as a dropdown instead of a free-form
 * input.  The backend doesn't currently expose a per-integration
 * capabilities endpoint, and spinning up one just to drive a select would
 * be overkill — the list of flagship models each vendor ships is public
 * and slow-moving enough to keep in a frontend constant.
 *
 * Shape
 *   { models: string[], custom: boolean }
 *
 *   • models — the vendor's current public model IDs, newest-first so
 *              the default option in the dropdown is the one people
 *              actually want.
 *   • custom — whether to also render a "Custom…" option that reveals a
 *              free-form input.  True for every known vendor (people
 *              use fine-tunes, preview models, region-specific IDs), so
 *              it's defaulted that way.
 *
 * Lookup
 *   `getModelsForProvider(name)` — case-insensitive match on integration
 *   display name.  Falls through to `null` when the provider isn't in
 *   the registry, which tells the modal to keep the old free-form text
 *   input.  Unknown providers should never lose the ability to type a
 *   value.
 *
 * Keeping this updated
 *   When a vendor ships a new flagship model, add it to the TOP of that
 *   provider's list.  We display models in array order, so the newest
 *   model is the first dropdown entry.  Drop models that have been
 *   retired by the vendor — don't just leave the list to grow.
 */

/** @type {Record<string, { models: string[], custom: boolean }>} */
const PROVIDER_MODELS = {
  anthropic: {
    models: [
      'claude-opus-4-6',
      'claude-sonnet-4-6',
      'claude-haiku-4-5',
      'claude-opus-4-5',
      'claude-sonnet-4-5',
      'claude-3-5-sonnet-20241022',
      'claude-3-5-haiku-20241022',
    ],
    custom: true,
  },

  openai: {
    models: [
      'gpt-4o',
      'gpt-4o-mini',
      'gpt-4-turbo',
      'o3',
      'o3-mini',
      'o1',
      'o1-mini',
    ],
    custom: true,
  },

  'amazon bedrock': {
    models: [
      'anthropic.claude-sonnet-4-6',
      'anthropic.claude-opus-4-6',
      'anthropic.claude-haiku-4-5',
      'meta.llama3-1-70b-instruct-v1:0',
      'meta.llama3-1-8b-instruct-v1:0',
      'amazon.titan-text-express-v1',
      'mistral.mistral-large-2407-v1:0',
    ],
    custom: true,
  },

  'google vertex': {
    models: [
      'gemini-2.0-flash',
      'gemini-1.5-pro',
      'gemini-1.5-flash',
      'text-embedding-005',
    ],
    custom: true,
  },

  gemini: {
    models: [
      'gemini-2.0-flash',
      'gemini-1.5-pro',
      'gemini-1.5-flash',
    ],
    custom: true,
  },

  mistral: {
    models: [
      'mistral-large-latest',
      'mistral-small-latest',
      'codestral-latest',
      'open-mixtral-8x22b',
      'open-mistral-nemo',
    ],
    custom: true,
  },

  cohere: {
    models: [
      'command-r-plus',
      'command-r',
      'command',
      'embed-english-v3.0',
    ],
    custom: true,
  },

  groq: {
    models: [
      'llama-3.3-70b-versatile',
      'llama-3.1-70b-versatile',
      'llama-3.1-8b-instant',
      'mixtral-8x7b-32768',
      'gemma2-9b-it',
    ],
    custom: true,
  },

  ollama: {
    // Ollama tags are wildly user-driven (llama3.2:3b-instruct-q5_K_M style)
    // so we list the common stems and lean on `custom: true` for the rest.
    models: [
      'llama3.2',
      'llama3.2:3b',
      'llama3.1',
      'qwen2.5',
      'mistral',
      'phi3',
      'gemma2',
    ],
    custom: true,
  },

  // HuggingFace inference endpoints — the "model" field is usually a
  // repo ID, so there's no sensible default list; we register it so the
  // modal shows an empty select with only the Custom… option.
  huggingface: {
    models: [],
    custom: true,
  },
}

/**
 * Look up the model registry for a provider by display name.
 * @param {string|null|undefined} name  integration display name ("Anthropic", "OpenAI", …)
 * @returns {{ models: string[], custom: boolean } | null}
 */
export function getModelsForProvider(name) {
  if (!name) return null
  const key = String(name).trim().toLowerCase()
  if (PROVIDER_MODELS[key]) return PROVIDER_MODELS[key]

  // A couple of tolerant aliases — these are cheap and keep the registry
  // from being fragile to small display-name variations that show up in
  // the integrations table.
  const aliases = {
    'aws bedrock':       'amazon bedrock',
    'bedrock':           'amazon bedrock',
    'google':            'google vertex',
    'vertex ai':         'google vertex',
    'vertex':            'google vertex',
    'google gemini':     'gemini',
    'hf':                'huggingface',
    'hugging face':      'huggingface',
  }
  const alias = aliases[key]
  return alias ? PROVIDER_MODELS[alias] : null
}

export { PROVIDER_MODELS }
