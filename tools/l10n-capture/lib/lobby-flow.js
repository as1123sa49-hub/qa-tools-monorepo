import { parseGameLocale, localeMatches } from './lang-url.js';
import { waitForUnityCanvas } from './browser-utils.js';
import { saveLangDebug } from './capture-debug.js';

async function selectEnvironment(page, portalEnv) {
  await page.getByRole('button', { name: 'Switch environment' }).click({ timeout: 10000 });
  await page.getByRole('menuitem', { name: portalEnv }).click({ timeout: 10000 });
  await page.waitForTimeout(600);
}

async function selectLanguage(page, portalLabel) {
  const openers = [
    () => page.getByRole('button', { name: 'Change language' }),
    () => page.getByRole('button', { name: /change language/i }),
    () => page.locator('header button, [class*="header"] button, nav button')
      .filter({ hasText: /文|语|English|語言/ }),
  ];
  let opened = false;
  for (const get of openers) {
    try {
      const btn = get().first();
      if (await btn.isVisible({ timeout: 1500 })) {
        await btn.click({ timeout: 8000 });
        opened = true;
        break;
      }
    } catch { /* try next */ }
  }
  if (!opened) {
    throw new Error('找不到語系切換按鈕（Change language / 地球圖示）');
  }
  await page.waitForTimeout(400);

  const pickers = [
    () => page.getByRole('menuitem', { name: portalLabel, exact: true }),
    () => page.getByRole('button', { name: portalLabel, exact: true }),
    () => page.getByText(portalLabel, { exact: true }),
  ];
  let picked = false;
  for (const get of pickers) {
    try {
      const el = get().first();
      if (await el.isVisible({ timeout: 2000 })) {
        await el.click({ timeout: 8000 });
        picked = true;
        break;
      }
    } catch { /* try next */ }
  }
  if (!picked) {
    throw new Error(`找不到語系選項：${portalLabel}`);
  }
  await page.waitForTimeout(600);
}

export async function prepareLobby(page, cfg, env, lang) {
  const envCfg = cfg.envMap[env];
  const langCfg = cfg.langMap[lang];
  if (!envCfg || !langCfg) {
    throw new Error(
      `未知 env/lang: ${env}/${lang}。請在 config.json 的 langMap 補上「${lang}」與 portalLabel（大廳語系選單顯示名稱）`,
    );
  }

  await page.goto(cfg.lobbyUrl, {
    waitUntil: 'domcontentloaded',
    timeout: cfg.timeouts.lobbyMs,
  });
  await page.waitForTimeout(1500);

  await selectEnvironment(page, envCfg.portalEnv);
  await selectLanguage(page, langCfg.portalLabel);
}

async function searchAndEnterSlot(page, slotId) {
  const search = page.locator('input[type="search"], input[placeholder*="搜"], input[placeholder*="Search"], input[type="text"]').first();
  await search.waitFor({ state: 'visible', timeout: 15000 });
  await search.fill('');
  await search.fill(slotId);
  await page.waitForTimeout(1200);

  const card = page.getByText(slotId, { exact: false }).first();
  await card.click({ timeout: 15000 });
}

async function reselectLobbyLanguage(page, cfg, env, lang, onLog) {
  const envCfg = cfg.envMap[env];
  const langCfg = cfg.langMap[lang];
  onLog?.('  [lang] 回大廳重選語系');
  await page.goto(cfg.lobbyUrl, {
    waitUntil: 'domcontentloaded',
    timeout: cfg.timeouts.lobbyMs,
  });
  await page.waitForTimeout(1500);
  await selectEnvironment(page, envCfg.portalEnv);
  await selectLanguage(page, langCfg.portalLabel);
  await saveLangDebug(cfg, 'lobby_after_reselect', page.url(), onLog);
}

async function waitForGamePage(page, cfg, env) {
  const expectedHost = cfg.envMap[env].gameHost;
  await page.waitForURL(u => u.hostname === expectedHost, { timeout: cfg.timeouts.gameLoadMs });
  const actual = new URL(page.url()).hostname;
  if (actual !== expectedHost) {
    throw new Error(
      `遊戲網域不符：預期 ${expectedHost}，實際 ${actual}（請確認大廳已選 ${cfg.envMap[env].portalEnv}）`,
    );
  }
  await page.waitForFunction(() => {
    const c = document.querySelector('#unity-canvas, canvas');
    return c && c.width > 100;
  }, { timeout: cfg.timeouts.gameLoadMs });
  await waitForUnityCanvas(page, cfg.timeouts.gameLoadMs);
  await page.waitForTimeout(2000);
}

/**
 * 進入遊戲並確認 URL ?l= 與目標語系一致；不符則回大廳重選後重試。
 */
export async function enterSlotWithLangCheck(page, cfg, env, lang, slotId, onLog) {
  const langCfg = cfg.langMap[lang];
  const checkCfg = cfg.langCheck || {};
  const enabled = checkCfg.enabled !== false;
  const maxRetries = checkCfg.maxRetries ?? 2;
  const urlParams = checkCfg.urlParams || ['l', 'lang', 'locale'];
  const expected = langCfg.urlCode || lang;
  const aliases = langCfg.urlAliases || [];

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    if (attempt > 1) {
      onLog?.(`  [lang] 語系不符，重試 ${attempt}/${maxRetries}`);
      await reselectLobbyLanguage(page, cfg, env, lang, onLog);
    }

    await searchAndEnterSlot(page, slotId);
    await waitForGamePage(page, cfg, env);

    const gameUrl = page.url();
    await saveLangDebug(cfg, `game_try${attempt}`, gameUrl, onLog);
    const actual = parseGameLocale(gameUrl, urlParams);

    if (!enabled) {
      onLog?.(`  [lang] 檢查已停用（l=${actual || '（無）'}）`);
      return;
    }

    onLog?.(`  [lang] 遊戲 URL l=${actual || '（無）'}，預期 ${expected}`);
    if (localeMatches(expected, actual, aliases)) {
      onLog?.('  [lang] 語系確認通過');
      return;
    }
  }

  const gameUrl = page.url();
  const actual = parseGameLocale(gameUrl, urlParams);
  throw new Error(
    `遊戲語系不符：URL l=${actual || '（無）'}，預期 ${expected}（請確認大廳語系或 RD 遊戲連結）\n${gameUrl}`,
  );
}
