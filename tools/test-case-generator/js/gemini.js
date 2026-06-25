// ─── Gemini 模型選項 ─────────────────────────────────────────
import {
  LLM_RETRY_STATUSES,
  LLM_MAX_RETRIES,
  awaitRetryDelay,
  formatLlmError
} from './llm-retry.js';

export const GEMINI_MODEL_STORAGE_KEY = 'gemini_model_id';
export const DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash';

export const GEMINI_MODELS = [
  {
    id: 'gemini-2.5-flash',
    label: 'Gemini 2.5 Flash（預設）',
    pros: '品質與速度平衡，JSON 結構化產出較穩定，適合一般規格書首次全量產出。',
    cons: '免費層額度最緊（約 5 RPM／20 RPD），多 PRD 分批或重試易觸發 429。'
  },
  {
    id: 'gemini-3.1-flash-lite',
    label: 'Gemini 3.1 Flash Lite（推薦省額度）',
    pros: '免費日額度最高（約 500 RPD、15 RPM），適合多規格分批、失敗重試、常態大量跑。',
    cons: '推理略弱於 2.5 Flash，複雜規格案例可能較少或較粗，產完建議抽查邊界與數值。'
  },
  {
    id: 'gemini-2.5-flash-lite',
    label: 'Gemini 2.5 Flash Lite',
    pros: '比 2.5 Flash 每分鐘請求較寬（約 10 RPM），速度仍快，適合中等篇幅規格。',
    cons: '每日請求仍約 20 RPD（與 2.5 Flash 同級），無法解決「今天額度已滿」；品質略低於 2.5 Flash。'
  },
  {
    id: 'gemini-3-flash-preview',
    label: 'Gemini 3 Flash（Preview）',
    pros: '新一代 Flash，邏輯與長文理解通常優於 2.5 系列，適合規則較多的 PRD。',
    cons: '免費層約 5 RPM／20 RPD，與 2.5 Flash 同級；Preview 可能調整，不同次產出波動可能較大。'
  }
];

/** @param {string} apiKey @param {string} prompt @param {string} modelId */
export async function callGemini(apiKey, prompt, modelId) {
  const url =
    `https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent?key=${apiKey}`;
  const body = JSON.stringify({
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: {
      responseMimeType: 'application/json',
      maxOutputTokens: 65536
    }
  });

  let lastErr = null;
  let lastStatus = 0;

  for (let attempt = 0; attempt < LLM_MAX_RETRIES; attempt++) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body
    });
    const data = await res.json().catch(() => ({}));

    if (res.ok) {
      const part = data.candidates?.[0]?.content?.parts?.[0];
      if (!part) throw new Error('AI 回傳格式異常，找不到輸出內容');
      return part.text || '';
    }

    lastStatus = res.status;
    const msg = data.error?.message || `API 錯誤 (${res.status})`;
    lastErr = new Error(msg);
    lastErr.status = res.status;

    if (LLM_RETRY_STATUSES.has(res.status) && attempt < LLM_MAX_RETRIES - 1) {
      await awaitRetryDelay(
        attempt + 1,
        res.status,
        msg,
        res.headers.get('Retry-After')
      );
      continue;
    }

    throw new Error(formatLlmError(lastErr, { provider: 'Gemini', status: res.status }));
  }

  throw new Error(
    formatLlmError(lastErr, { provider: 'Gemini', status: lastStatus }) || 'API 呼叫失敗'
  );
}
