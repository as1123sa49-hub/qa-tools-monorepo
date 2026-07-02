import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TOOL_ROOT = path.resolve(__dirname, '..');

const USER_ID_MAX_LEN = 64;

/**
 * 將外部傳入的 userId 淨化成可當目錄名的字串；空值為 default。
 * @param {unknown} raw
 * @returns {string}
 */
export function sanitizeUserId(raw) {
  const s = String(raw ?? '').trim();
  if (!s) return 'default';
  const safe = s.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, USER_ID_MAX_LEN);
  return safe || 'default';
}

/**
 * 使用者工作區根目錄：data/{userId}/
 * @param {unknown} userId
 * @returns {string}
 */
export function userRoot(userId) {
  return path.join(TOOL_ROOT, 'data', sanitizeUserId(userId));
}

/**
 * 使用者登入狀態檔（結構同 config.authFile，位於工作區內）。
 * @param {unknown} userId
 * @param {object} cfg
 * @returns {string}
 */
export function userAuthPath(userId, cfg) {
  const rel = cfg.authFile || '.auth/lobby.json';
  return path.join(userRoot(userId), rel);
}

/**
 * 使用者擷取產出根目錄：data/{userId}/captures/
 * @param {unknown} userId
 * @param {object} cfg
 * @returns {string}
 */
export function userOutputRoot(userId, cfg) {
  return path.join(userRoot(userId), cfg.outputRoot || 'captures');
}

/**
 * 從 HTTP 請求解析 userId（Header > body > query）。
 * @param {import('express').Request} req
 * @returns {string}
 */
export function resolveUserIdFromRequest(req) {
  const fromHeader = req.get?.('X-User-Id') ?? req.headers?.['x-user-id'];
  const fromBody = req.body?.userId;
  const fromQuery = req.query?.userId;
  return sanitizeUserId(fromHeader || fromBody || fromQuery);
}
