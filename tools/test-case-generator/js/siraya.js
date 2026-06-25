// ─── Siraya 模型選項（Gemini / GPT / Claude）──────────────────
import {
  LLM_RETRY_STATUSES,
  LLM_MAX_RETRIES,
  awaitRetryDelay,
  formatLlmError
} from './llm-retry.js';

export const SIRAYA_MODEL_STORAGE_KEY = 'siraya_model_id';
export const SIRAYA_API_KEY_STORAGE_KEY = 'siraya_api_key';
export const DEFAULT_SIRAYA_MODEL = 'gemini-2.5-flash';
export const SIRAYA_BASE_URL = 'https://llm.siraya.ai/v1';

export const SIRAYA_MODELS = [
  {
    id: 'gemini-2.5-flash',
    label: 'Gemini 2.5 Flash（預設）',
    group: 'Gemini',
    pros: '品質與速度平衡，JSON 結構化產出較穩定，適合一般規格書全量產出。',
    cons: 'Siraya 按用量計費，長 PRD 分批會累積 token 費用。'
  },
  {
    id: 'gemini-2.5-flash-lite',
    label: 'Gemini 2.5 Flash Lite',
    group: 'Gemini',
    pros: '比 2.5 Flash 更快更省，適合多規格分批與重試。',
    cons: '複雜規格案例可能較少或較粗，產完建議抽查邊界。'
  },
  {
    id: 'gemini-2.5-pro',
    label: 'Gemini 2.5 Pro',
    group: 'Gemini',
    pros: '長文理解與複雜規則較強，適合大型後台 PRD。',
    cons: '速度較慢、費用較高，不建議大量分批預設使用。'
  },
  {
    id: 'gemini-3-flash-preview',
    label: 'Gemini 3 Flash（Preview）',
    group: 'Gemini',
    pros: '新一代 Flash，邏輯與長文理解通常優於 2.5 系列。',
    cons: 'Preview 可能調整，不同次產出波動可能較大。'
  },
  {
    id: 'gemini-3.1-pro-preview',
    label: 'Gemini 3.1 Pro（Preview）',
    group: 'Gemini',
    pros: '複雜規格、多模組後台品質優先時可試。',
    cons: '費用與延遲較高，Preview 穩定性待觀察。'
  },
  {
    id: 'gpt-4o-mini',
    label: 'GPT-4o mini（GPT 預設）',
    group: 'GPT',
    pros: '便宜、速度快，JSON 結構化通常穩定，適合大量產出。',
    cons: '超長 PRD 或細碎規則時可能漏案例。'
  },
  {
    id: 'gpt-4o',
    label: 'GPT-4o',
    group: 'GPT',
    pros: '品質與速度平衡，指令遵循佳。',
    cons: '比 mini 貴，極長規格仍可能需分批。'
  },
  {
    id: 'gpt-4.1-mini',
    label: 'GPT-4.1 mini',
    group: 'GPT',
    pros: '4.1 系列輕量版，性價比佳。',
    cons: '與 4o mini 表現接近，依帳號定價選用。'
  },
  {
    id: 'gpt-5.2',
    label: 'GPT-5.2',
    group: 'GPT',
    pros: '旗艦推理與結構化能力，複雜規格可試。',
    cons: '費用最高、延遲較長，不建議常態大量跑。'
  },
  {
    id: 'claude-sonnet-4.6',
    label: 'Claude Sonnet 4.6（Claude 預設）',
    group: 'Claude',
    pros: '長文 PRD 與規則梳理表現佳，產出品質穩定。',
    cons: '比 Haiku 慢且貴，極大量分批需注意成本。'
  },
  {
    id: 'claude-haiku-4.5',
    label: 'Claude Haiku 4.5',
    group: 'Claude',
    pros: '快、便宜，適合模組化 AI 確認等輔助任務。',
    cons: '複雜全量產出可能不如 Sonnet 完整。'
  },
  {
    id: 'claude-opus-4.6',
    label: 'Claude Opus 4.6',
    group: 'Claude',
    pros: '最強推理，最難規格與邊界案例可優先考慮。',
    cons: '最慢、最貴，僅建議少數高價值規格使用。'
  }
];

/** @param {string} apiKey @param {string} prompt @param {string} modelId */
export async function callSiraya(apiKey, prompt, modelId) {
  const url = `${SIRAYA_BASE_URL}/chat/completions`;
  const body = JSON.stringify({
    model: modelId,
    messages: [{ role: 'user', content: prompt }],
    response_format: { type: 'json_object' },
    max_tokens: 65536
  });

  let lastErr = null;
  let lastStatus = 0;

  for (let attempt = 0; attempt < LLM_MAX_RETRIES; attempt++) {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      },
      body
    });
    const data = await res.json().catch(() => ({}));

    if (res.ok) {
      const content = data.choices?.[0]?.message?.content;
      if (!content) throw new Error('AI 回傳格式異常，找不到輸出內容');
      return content;
    }

    lastStatus = res.status;
    const msg = data.error?.message || data.message || `API 錯誤 (${res.status})`;
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

    throw new Error(formatLlmError(lastErr, { provider: 'Siraya', status: res.status }));
  }

  throw new Error(formatLlmError(lastErr, { provider: 'Siraya', status: lastStatus })
    || 'API 呼叫失敗');
}
