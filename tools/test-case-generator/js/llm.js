import {
  callGemini,
  GEMINI_MODELS,
  GEMINI_MODEL_STORAGE_KEY,
  DEFAULT_GEMINI_MODEL
} from './gemini.js';
import {
  callSiraya,
  SIRAYA_MODELS,
  SIRAYA_MODEL_STORAGE_KEY,
  DEFAULT_SIRAYA_MODEL,
  SIRAYA_API_KEY_STORAGE_KEY
} from './siraya.js';

export const LLM_PROVIDER_STORAGE_KEY = 'llm_provider';
export const PROVIDER_GEMINI = 'gemini';
export const PROVIDER_SIRAYA = 'siraya';
export const GEMINI_API_KEY_STORAGE_KEY = 'gemini_api_key';

/** @returns {'gemini'|'siraya'} */
export function getLlmProvider() {
  const sel = document.getElementById('llmProviderSelect');
  const fromUi = sel?.value?.trim();
  if (fromUi === PROVIDER_GEMINI || fromUi === PROVIDER_SIRAYA) return fromUi;
  const saved = localStorage.getItem(LLM_PROVIDER_STORAGE_KEY);
  if (saved === PROVIDER_GEMINI || saved === PROVIDER_SIRAYA) return saved;
  return PROVIDER_GEMINI;
}

export function getApiKeyStorageKey(provider = getLlmProvider()) {
  return provider === PROVIDER_SIRAYA ? SIRAYA_API_KEY_STORAGE_KEY : GEMINI_API_KEY_STORAGE_KEY;
}

export function getModelsForProvider(provider = getLlmProvider()) {
  return provider === PROVIDER_SIRAYA ? SIRAYA_MODELS : GEMINI_MODELS;
}

export function getDefaultModelForProvider(provider = getLlmProvider()) {
  return provider === PROVIDER_SIRAYA ? DEFAULT_SIRAYA_MODEL : DEFAULT_GEMINI_MODEL;
}

export function getModelStorageKey(provider = getLlmProvider()) {
  return provider === PROVIDER_SIRAYA ? SIRAYA_MODEL_STORAGE_KEY : GEMINI_MODEL_STORAGE_KEY;
}

export function getSelectedModelId(provider = getLlmProvider()) {
  const models = getModelsForProvider(provider);
  const defaultId = getDefaultModelForProvider(provider);
  const sel = document.getElementById('llmModelSelect');
  const fromUi = sel?.value?.trim();
  if (fromUi && models.some(m => m.id === fromUi)) return fromUi;
  const saved = localStorage.getItem(getModelStorageKey(provider));
  if (saved && models.some(m => m.id === saved)) return saved;
  return defaultId;
}

export function getProviderLabel(provider = getLlmProvider()) {
  return provider === PROVIDER_SIRAYA ? 'Siraya' : 'Gemini';
}

export function getApiKeyLabel(provider = getLlmProvider()) {
  return provider === PROVIDER_SIRAYA ? 'Siraya API Key' : 'Gemini API Key';
}

export function renderModelOptions(models) {
  if (models[0]?.group) {
    const groups = {};
    for (const m of models) {
      (groups[m.group] ||= []).push(m);
    }
    return Object.entries(groups).map(([group, items]) =>
      `<optgroup label="${group}">${
        items.map(m => `<option value="${m.id}">${m.label}</option>`).join('')
      }</optgroup>`
    ).join('');
  }
  return models.map(m => `<option value="${m.id}">${m.label}</option>`).join('');
}

/** @param {'gemini'|'siraya'} provider @param {string} apiKey @param {string} prompt @param {string} modelId */
export async function callLlm(provider, apiKey, prompt, modelId) {
  if (provider === PROVIDER_SIRAYA) {
    return callSiraya(apiKey, prompt, modelId);
  }
  return callGemini(apiKey, prompt, modelId);
}

export {
  formatLlmError as formatApiError,
  sleep as llmSleep,
  MULTI_BATCH_THROTTLE_MS
} from './llm-retry.js';
