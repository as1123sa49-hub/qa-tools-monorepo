export const PROVIDER_GEMINI = 'gemini';
export const PROVIDER_SIRAYA = 'siraya';

export const GEMINI_API_KEY_STORAGE_KEY = 'gemini_api_key';
export const SIRAYA_API_KEY_STORAGE_KEY = 'siraya_api_key';
export const LLM_PROVIDER_STORAGE_KEY = 'llm_provider';
export const GEMINI_MODEL_STORAGE_KEY = 'gemini_model_id';
export const SIRAYA_MODEL_STORAGE_KEY = 'siraya_model_id';

export const DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash';
export const DEFAULT_SIRAYA_MODEL = 'gemini-2.5-flash';
export const SIRAYA_BASE_URL = 'https://llm.siraya.ai/v1';

export const GEMINI_MODELS = [
  { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash（預設）' },
  { id: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash Lite' },
  { id: 'gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash Lite（省額度）' },
];

export const SIRAYA_MODELS = [
  { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash（預設）', group: 'Gemini' },
  { id: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash Lite', group: 'Gemini' },
  { id: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro', group: 'Gemini' },
  { id: 'gemini-3-flash-preview', label: 'Gemini 3 Flash（Preview）', group: 'Gemini' },
  { id: 'gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash Lite', group: 'Gemini' },
  { id: 'gpt-4o-mini', label: 'GPT-4o mini', group: 'GPT' },
  { id: 'gpt-4o', label: 'GPT-4o', group: 'GPT' },
  { id: 'gpt-4.1-mini', label: 'GPT-4.1 mini', group: 'GPT' },
  { id: 'claude-sonnet-4.6', label: 'Claude Sonnet 4.6', group: 'Claude' },
  { id: 'claude-haiku-4.5', label: 'Claude Haiku 4.5', group: 'Claude' },
  { id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash（省額度）', group: 'DeepSeek' },
  { id: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro', group: 'DeepSeek' },
];

export function getModelsForProvider(provider) {
  return provider === PROVIDER_SIRAYA ? SIRAYA_MODELS : GEMINI_MODELS;
}

export function getDefaultModelForProvider(provider) {
  return provider === PROVIDER_SIRAYA ? DEFAULT_SIRAYA_MODEL : DEFAULT_GEMINI_MODEL;
}

export function getApiKeyStorageKey(provider) {
  return provider === PROVIDER_SIRAYA ? SIRAYA_API_KEY_STORAGE_KEY : GEMINI_API_KEY_STORAGE_KEY;
}

export function getModelStorageKey(provider) {
  return provider === PROVIDER_SIRAYA ? SIRAYA_MODEL_STORAGE_KEY : GEMINI_MODEL_STORAGE_KEY;
}

export function getApiKeyLabel(provider) {
  return provider === PROVIDER_SIRAYA ? 'Siraya API Key' : 'Gemini API Key';
}
