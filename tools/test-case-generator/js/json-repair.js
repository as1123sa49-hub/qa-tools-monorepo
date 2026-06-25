/** 修復截斷 JSON（來自 n8n Code 節點） */
export function fixTruncatedJson(jsonString) {
  try {
    JSON.parse(jsonString);
    return { text: jsonString, truncated: false };
  } catch (_) {
    const lastOpenBrace = jsonString.lastIndexOf('{');
    if (lastOpenBrace === -1) return { text: '[]', truncated: true };

    let fixed = jsonString.substring(0, lastOpenBrace).trim();
    if (fixed.endsWith(',')) fixed = fixed.slice(0, -1);
    fixed += '\n]';

    try {
      JSON.parse(fixed);
      return { text: fixed, truncated: true };
    } catch (_) {
      return { text: fixed.replace(/,$/, '') + ']', truncated: true };
    }
  }
}

/** 修復 JSON 字串值內未跳脫的換行／控制字元 */
export function repairJsonControlChars(jsonString) {
  let result = '';
  let inString = false;
  let escaped = false;
  for (let i = 0; i < jsonString.length; i++) {
    const ch = jsonString[i];
    if (escaped) {
      result += ch;
      escaped = false;
      continue;
    }
    if (ch === '\\' && inString) {
      result += ch;
      escaped = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      result += ch;
      continue;
    }
    if (inString) {
      if (ch === '\n') { result += '\\n'; continue; }
      if (ch === '\r') { result += '\\r'; continue; }
      if (ch === '\t') { result += '\\t'; continue; }
      if (ch.charCodeAt(0) < 32) continue;
    }
    result += ch;
  }
  return result;
}
