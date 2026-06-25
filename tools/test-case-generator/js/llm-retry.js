/** LLM API 重試、節流與友善錯誤訊息 */

export const LLM_RETRY_STATUSES = new Set([429, 500, 502, 503, 504]);
export const LLM_MAX_RETRIES = 5;
/** 多規格分批之間的最小間隔（避免 Gemini 免費層 RPM 超限） */
export const MULTI_BATCH_THROTTLE_MS = 5000;

export function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

/** 從 Retry-After 標頭或錯誤訊息「retry in 40.5s」解析等待毫秒 */
export function parseRetryDelayMs(message, retryAfterHeader) {
  if (retryAfterHeader != null && retryAfterHeader !== '') {
    const sec = parseFloat(String(retryAfterHeader).trim());
    if (!Number.isNaN(sec) && sec > 0) return Math.ceil(sec * 1000);
  }
  const m = (message || '').match(/retry\s+in\s+([\d.]+)\s*s/i);
  if (m) {
    const ms = Math.ceil(parseFloat(m[1]) * 1000);
    if (ms > 0) return ms;
  }
  return null;
}

export function computeRetryDelayMs(attempt, status, message, retryAfterHeader) {
  const suggested = parseRetryDelayMs(message, retryAfterHeader);
  const exponential = Math.min(2000 * Math.pow(2, Math.max(0, attempt - 1)), 15000);
  if (status === 429) {
    const base = suggested ?? exponential;
    return Math.min(Math.max(base + 500, exponential), 90000);
  }
  return suggested ?? exponential;
}

export async function awaitRetryDelay(attempt, status, message, retryAfterHeader) {
  const ms = computeRetryDelayMs(attempt, status, message, retryAfterHeader);
  await sleep(ms);
  return ms;
}

export function isQuotaOrRateLimitError(message, status) {
  if (status === 429) return true;
  const m = (message || '').toLowerCase();
  return m.includes('quota')
    || m.includes('rate limit')
    || m.includes('resource_exhausted')
    || m.includes('too many requests');
}

/**
 * 將 API 原始錯誤轉為簡短中文說明（429／額度）
 * @param {Error|string} err
 * @param {{ provider?: string, status?: number }} opts
 */
export function formatLlmError(err, { provider = 'Gemini', status } = {}) {
  const raw = (err && err.message) ? err.message : String(err || '');
  const st = status ?? err?.status;
  if (!isQuotaOrRateLimitError(raw, st)) return raw;

  const retryMs = parseRetryDelayMs(raw, null);
  const waitHint = retryMs
    ? `建議等待約 ${Math.ceil(retryMs / 1000)} 秒後再試。`
    : '建議等待 1～2 分鐘後再試。';

  const isGemini = provider !== 'Siraya';
  const tips = isGemini
    ? '可改用「Gemini 3.1 Flash Lite」、拉長分批間隔，或切換 Siraya。'
    : '請稍後再試，或至 Siraya 控制台檢查用量。';

  if (/exceeded your current quota|quota/i.test(raw)) {
    return `${provider} 額度已用完或請求過於頻繁。${waitHint} ${tips}`;
  }
  if (st === 429 || /rate limit|too many requests/i.test(raw)) {
    return `${provider} API 請求過於頻繁（429）。${waitHint} ${tips}`;
  }
  return raw;
}
