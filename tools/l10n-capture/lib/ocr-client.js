import {
  PROVIDER_GEMINI,
  PROVIDER_SIRAYA,
  SIRAYA_BASE_URL,
} from './llm-providers.js';

export const OCR_PROMPT =
  'Extract ALL visible text from this screenshot. Return ONLY the extracted text in its original language and script. Preserve numbers and symbols. Do not translate. Do not add explanations or markdown.';

const RETRY_STATUSES = new Set([429, 500, 502, 503, 504]);
const MAX_RETRIES = 4;

const sleep = ms => new Promise(r => setTimeout(r, ms));

export function createUsageAccumulator() {
  return {
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
    imageTokens: 0,
    cachedTokens: 0,
    reasoningTokens: 0,
    costUsd: 0,
    apiCostReported: false,
  };
}

export function mergeUsage(acc, usage, cost) {
  if (!acc || !usage) return;
  acc.promptTokens += usage.prompt_tokens ?? usage.promptTokenCount ?? 0;
  acc.completionTokens += usage.completion_tokens ?? usage.candidatesTokenCount ?? 0;
  acc.totalTokens += usage.total_tokens ?? usage.totalTokenCount ?? 0;
  const inDetails = usage.prompt_tokens_details;
  if (inDetails) {
    acc.imageTokens += inDetails.image_tokens ?? 0;
    acc.cachedTokens += inDetails.cached_tokens ?? 0;
  }
  const outDetails = usage.completion_tokens_details;
  if (outDetails) acc.reasoningTokens += outDetails.reasoning_tokens ?? 0;
  if (cost != null && Number.isFinite(Number(cost))) {
    acc.costUsd += Number(cost);
    acc.apiCostReported = true;
  }
}

async function fetchWithRetry(url, init) {
  let lastErr = null;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    const res = await fetch(url, init);
    const json = await res.json().catch(() => ({}));
    if (res.ok) return json;
    const msg = json.error?.message || json.message || `API 錯誤 (${res.status})`;
    lastErr = new Error(msg);
    if (RETRY_STATUSES.has(res.status) && attempt < MAX_RETRIES - 1) {
      await sleep(1000 * 2 ** attempt);
      continue;
    }
    throw lastErr;
  }
  throw lastErr || new Error('OCR 失敗');
}

async function ocrGeminiParts(apiKey, modelId, images, prompt, maxOutputTokens = 4096, usageAcc = null) {
  const parts = [{ text: prompt }];
  for (const { buffer, mimeType } of images) {
    parts.push({ inline_data: { mime_type: mimeType, data: Buffer.from(buffer).toString('base64') } });
  }
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent?key=${apiKey}`;
  const json = await fetchWithRetry(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ parts }],
      generationConfig: { temperature: 0, maxOutputTokens },
    }),
  });
  mergeUsage(usageAcc, json.usageMetadata);
  const out = json.candidates?.[0]?.content?.parts || [];
  return out.map(p => p.text || '').join('').trim();
}

async function ocrSirayaParts(apiKey, modelId, images, prompt, maxOutputTokens = 4096, usageAcc = null) {
  const content = [{ type: 'text', text: prompt }];
  for (const { buffer, mimeType } of images) {
    const data = Buffer.from(buffer).toString('base64');
    content.push({ type: 'image_url', image_url: { url: `data:${mimeType};base64,${data}` } });
  }
  const url = `${SIRAYA_BASE_URL}/chat/completions`;
  const payload = {
    model: modelId,
    messages: [{ role: 'user', content }],
    temperature: 0,
    max_tokens: maxOutputTokens,
  };
  if (/^deepseek/i.test(modelId)) {
    payload.thinking = { type: 'disabled' };
  }
  const json = await fetchWithRetry(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(payload),
  });
  mergeUsage(usageAcc, json.usage, json.cost ?? json.usage?.cost);
  const body = json.choices?.[0]?.message?.content;
  const text = typeof body === 'string'
    ? body.trim()
    : Array.isArray(body)
      ? body.filter(p => p.type === 'text').map(p => p.text || '').join('').trim()
      : '';
  if (!text) {
    const reason = json.choices?.[0]?.finish_reason;
    throw new Error(reason ? `AI 未回傳任何文字（${reason}）` : 'AI 未回傳任何文字');
  }
  return text;
}

/** 對單張圖呼叫 Vision OCR（Gemini 直連或 Siraya） */
export async function ocrImage({
  provider = PROVIDER_GEMINI,
  apiKey,
  modelId,
  buffer,
  mimeType = 'image/png',
  maxOutputTokens = 4096,
  usageAcc = null,
  prompt = OCR_PROMPT,
}) {
  if (provider === PROVIDER_SIRAYA) {
    return ocrSirayaParts(apiKey, modelId, [{ buffer, mimeType }], prompt, maxOutputTokens, usageAcc);
  }
  return ocrGeminiParts(apiKey, modelId, [{ buffer, mimeType }], prompt, maxOutputTokens, usageAcc);
}

/** 多張圖一次 Vision OCR（Gemini 或 Siraya） */
export async function ocrMultiImages(provider, apiKey, modelId, prepared, prompt, maxOutputTokens, usageAcc = null) {
  if (provider === PROVIDER_SIRAYA) {
    return ocrSirayaParts(apiKey, modelId, prepared, prompt, maxOutputTokens, usageAcc);
  }
  return ocrGeminiParts(apiKey, modelId, prepared, prompt, maxOutputTokens, usageAcc);
}
