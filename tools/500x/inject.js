/**
 * Bonus ColorGame V2 — 電子骰機率驗證工具
 * 使用方式：開啟遊戲頁面後，貼到瀏覽器 Console 執行
 *
 * 攔截 WebSocket 訊息 → 即時統計電子骰倍率 → 匯出 CSV
 */
(function () {
  'use strict';

  // ─── 防止重複注入 ────────────────────────────────────────
  if (window.__bonusV2Checker) {
    const p = document.getElementById('__bonusV2Panel');
    if (p) { p.style.display = 'block'; }
    console.log('[BonusV2] 工具已在運行，面板已顯示');
    return;
  }
  window.__bonusV2Checker = true;

  // ─── V2 規格書期望值 ──────────────────────────────────────
  const V2_SPEC = {
    m2: {
      label: 'Single 2同',
      rates: [3, 4, 6, 8, 10],
      weights: { 3: 64, 4: 64, 6: 39, 8: 22, 10: 11 },
      total: 200
    },
    m3: {
      label: 'Single 3同',
      rates: [10, 20, 30, 60, 100],
      weights: { 10: 52, 20: 52, 30: 44, 60: 30, 100: 22 },
      total: 200
    },
    ad: {
      label: 'AnyDouble',
      rates: [2, 3, 5, 10, 20],
      weights: { 2: 86, 3: 57, 5: 33, 10: 16, 20: 8 },
      total: 200
    },
    at: {
      label: 'AnyTriple',
      rates: [50, 100, 150, 250, 500],
      weights: { 50: 100, 100: 49, 150: 30, 250: 14, 500: 7 },
      total: 200
    }
  };

  const COLOR_MAP = { 801: '黃', 802: '白', 803: '粉', 804: '藍', 805: '紅', 806: '綠' };

  // ─── 狀態 ─────────────────────────────────────────────────
  const state = {
    totalRounds: 0,
    m2: { total: 0, counts: {} },
    m3: { total: 0, counts: {} },
    ad: { total: 0, counts: {} },
    at: { total: 0, counts: {} }
  };
  const allRounds = [];
  const processedRounds = new Set();

  // ─── 解析電子骰資料 ───────────────────────────────────────
  function parseBonusData(data143) {
    const result = { single_m2: [], single_m3: [], any_double: null, any_triple: null };
    for (const [key, val] of Object.entries(data143)) {
      const k = Number(key);
      if (k >= 801 && k <= 806) {
        const color = COLOR_MAP[k] || String(k);
        if (val.matchColors === 2) result.single_m2.push({ color, rate: val.rate });
        else if (val.matchColors === 3) result.single_m3.push({ color, rate: val.rate });
      } else if (k === 807) {
        result.any_double = { color: COLOR_MAP[val.bonusColor] || String(val.bonusColor), rate: val.rate };
      } else if (k === 808) {
        result.any_triple = { color: COLOR_MAP[val.bonusColor] || String(val.bonusColor), rate: val.rate };
      }
    }
    return result;
  }

  // ─── 處理 WS 訊息 ─────────────────────────────────────────
  function processMessage(raw) {
    try {
      if (typeof raw !== 'string') return;
      if (raw.startsWith('$#|#$')) raw = raw.slice(5);
      if (!raw.startsWith('{')) return;

      const data = JSON.parse(raw);
      if (data.e !== 'notify' || data.d?.v?.[3] !== 'prepareBonusResult') return;

      const roundId = data.d?.v?.[10]?.[0];
      if (roundId && processedRounds.has(roundId)) return;
      if (roundId) processedRounds.add(roundId);

      const data143 = data.d?.v?.[10]?.[143];
      if (!data143 || typeof data143 !== 'object' || !Object.keys(data143).length) return;

      const parsed = parseBonusData(data143);
      state.totalRounds++;

      for (const item of (parsed.single_m2 || [])) {
        state.m2.total++;
        state.m2.counts[item.rate] = (state.m2.counts[item.rate] || 0) + 1;
      }
      for (const item of (parsed.single_m3 || [])) {
        state.m3.total++;
        state.m3.counts[item.rate] = (state.m3.counts[item.rate] || 0) + 1;
      }
      if (parsed.any_double) {
        state.ad.total++;
        const r = parsed.any_double.rate;
        state.ad.counts[r] = (state.ad.counts[r] || 0) + 1;
      }
      if (parsed.any_triple) {
        state.at.total++;
        const r = parsed.any_triple.rate;
        state.at.counts[r] = (state.at.counts[r] || 0) + 1;
      }

      allRounds.push({
        round: state.totalRounds,
        time: new Date().toLocaleTimeString('zh-TW', { hour12: false }),
        ...parsed
      });

      updatePanel();
    } catch (_) { /* 略過 */ }
  }

  // ─── WebSocket 攔截（現有 + 未來連線）────────────────────
  const origDispatchEvent = WebSocket.prototype.dispatchEvent;
  WebSocket.prototype.dispatchEvent = function (event) {
    if (event.type === 'message' && typeof event.data === 'string') {
      processMessage(event.data);
    }
    return origDispatchEvent.call(this, event);
  };

  const OrigWS = window.WebSocket;
  function PatchedWS(url, protocols) {
    const ws = protocols ? new OrigWS(url, protocols) : new OrigWS(url);
    ws.addEventListener('message', e => { if (typeof e.data === 'string') processMessage(e.data); });
    return ws;
  }
  PatchedWS.prototype = OrigWS.prototype;
  Object.setPrototypeOf(PatchedWS, OrigWS);
  window.WebSocket = PatchedWS;

  // ─── 面板樣式 ─────────────────────────────────────────────
  const PANEL_ID = '__bonusV2Panel';
  const CSS = `
    #${PANEL_ID} {
      position: fixed; top: 20px; right: 20px; z-index: 2147483647;
      width: 380px; background: #1a1b1e; border: 1px solid #373a40;
      border-radius: 10px; box-shadow: 0 8px 32px rgba(0,0,0,.7);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft JhengHei', sans-serif;
      font-size: 12px; color: #c9d1d9; user-select: none;
    }
    #${PANEL_ID} * { box-sizing: border-box; margin: 0; padding: 0; }
    #${PANEL_ID} .bv2-hdr {
      display: flex; justify-content: space-between; align-items: center;
      padding: 10px 14px; background: #25262b;
      border-radius: 10px 10px 0 0; border-bottom: 1px solid #373a40;
      cursor: move;
    }
    #${PANEL_ID} .bv2-hdr-left { display: flex; align-items: center; gap: 8px; }
    #${PANEL_ID} .bv2-title { font-weight: 700; font-size: 13px; color: #e9ecef; }
    #${PANEL_ID} .bv2-count { font-size: 11px; color: #51cf66; font-weight: 600; }
    #${PANEL_ID} .bv2-hdr-right { display: flex; gap: 6px; align-items: center; }
    #${PANEL_ID} .bv2-btn-sm {
      background: #373a40; border: none; color: #868e96;
      border-radius: 4px; padding: 3px 8px; font-size: 11px;
      cursor: pointer; transition: background .15s;
    }
    #${PANEL_ID} .bv2-btn-sm:hover { background: #495057; color: #dee2e6; }
    #${PANEL_ID} .bv2-body {
      padding: 10px 12px; max-height: 75vh; overflow-y: auto;
    }
    #${PANEL_ID} .bv2-section { margin-bottom: 10px; }
    #${PANEL_ID} .bv2-section-title {
      font-size: 11px; font-weight: 700; color: #74c0fc;
      display: flex; justify-content: space-between;
      padding-bottom: 5px; border-bottom: 1px solid #373a40; margin-bottom: 5px;
    }
    #${PANEL_ID} .bv2-section-sub { font-weight: 400; color: #6e7681; }
    #${PANEL_ID} table { width: 100%; border-collapse: collapse; }
    #${PANEL_ID} th {
      text-align: right; padding: 2px 6px 4px;
      color: #6e7681; font-size: 10px; font-weight: 600;
      border-bottom: 1px solid #373a40;
    }
    #${PANEL_ID} th:first-child { text-align: left; }
    #${PANEL_ID} td {
      padding: 4px 6px; text-align: right;
      border-bottom: 1px solid #2c2e33;
      font-variant-numeric: tabular-nums;
    }
    #${PANEL_ID} td:first-child { text-align: left; font-weight: 600; }
    #${PANEL_ID} tr:last-child td { border-bottom: none; }
    #${PANEL_ID} .ok   { color: #51cf66; }
    #${PANEL_ID} .warn { color: #ffd43b; }
    #${PANEL_ID} .bad  { color: #ff6b6b; }
    #${PANEL_ID} .none { color: #6e7681; }
    #${PANEL_ID} .bv2-export-row { display: flex; gap: 8px; margin-top: 8px; }
    #${PANEL_ID} .bv2-export-btn {
      flex: 1; padding: 7px 0; background: #1971c2; color: #fff;
      border: none; border-radius: 6px; cursor: pointer;
      font-size: 11px; font-weight: 600; transition: background .15s;
    }
    #${PANEL_ID} .bv2-export-btn:hover { background: #1864ab; }
    #${PANEL_ID} .bv2-clear-btn {
      padding: 7px 12px; background: #373a40; color: #dee2e6;
      border: none; border-radius: 6px; cursor: pointer;
      font-size: 11px; transition: background .15s;
    }
    #${PANEL_ID} .bv2-clear-btn:hover { background: #495057; }
    #${PANEL_ID} ::-webkit-scrollbar { width: 4px; }
    #${PANEL_ID} ::-webkit-scrollbar-track { background: transparent; }
    #${PANEL_ID} ::-webkit-scrollbar-thumb { background: #373a40; border-radius: 2px; }
  `;

  // ─── 建立面板 ─────────────────────────────────────────────
  function createPanel() {
    if (document.getElementById(PANEL_ID)) return;

    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    const panel = document.createElement('div');
    panel.id = PANEL_ID;
    panel.innerHTML = `
      <div class="bv2-hdr" id="__bv2Hdr">
        <div class="bv2-hdr-left">
          <span class="bv2-title">🎲 Bonus V2 電子骰驗證</span>
          <span class="bv2-count" id="__bv2Count">0 局</span>
        </div>
        <div class="bv2-hdr-right">
          <button class="bv2-btn-sm" id="__bv2Min">—</button>
        </div>
      </div>
      <div class="bv2-body" id="__bv2Body">
        ${['m2','m3','ad','at'].map(key => `
          <div class="bv2-section">
            <div class="bv2-section-title">
              <span>▌ ${V2_SPEC[key].label}</span>
              <span class="bv2-section-sub" id="__bv2Sub_${key}">共 0 次抽中</span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>倍率</th><th>期望%</th><th>次數</th><th>實際%</th><th>差值</th>
                </tr>
              </thead>
              <tbody id="__bv2Tbody_${key}">
                ${V2_SPEC[key].rates.map(rate => {
                  const exp = (V2_SPEC[key].weights[rate] / V2_SPEC[key].total * 100).toFixed(1);
                  return `<tr>
                    <td>${rate}x</td>
                    <td>${exp}%</td>
                    <td id="__bv2Cnt_${key}_${rate}">0</td>
                    <td id="__bv2Pct_${key}_${rate}">—</td>
                    <td id="__bv2Diff_${key}_${rate}" class="none">—</td>
                  </tr>`;
                }).join('')}
              </tbody>
            </table>
          </div>
        `).join('')}

        <div class="bv2-export-row">
          <button class="bv2-export-btn" id="__bv2ExStats">📊 統計 CSV</button>
          <button class="bv2-export-btn" id="__bv2ExDetail">📋 明細 CSV</button>
          <button class="bv2-clear-btn" id="__bv2Clear">清空</button>
        </div>
      </div>`;

    document.body.appendChild(panel);
    bindEvents(panel);
  }

  // ─── 更新統計面板 ─────────────────────────────────────────
  function updatePanel() {
    const countEl = document.getElementById('__bv2Count');
    if (countEl) countEl.textContent = `${state.totalRounds} 局`;

    for (const key of ['m2', 'm3', 'ad', 'at']) {
      const cat = state[key];
      const spec = V2_SPEC[key];
      const sub = document.getElementById(`__bv2Sub_${key}`);
      if (sub) sub.textContent = `共 ${cat.total} 次抽中`;

      for (const rate of spec.rates) {
        const count = cat.counts[rate] || 0;
        const cntEl  = document.getElementById(`__bv2Cnt_${key}_${rate}`);
        const pctEl  = document.getElementById(`__bv2Pct_${key}_${rate}`);
        const diffEl = document.getElementById(`__bv2Diff_${key}_${rate}`);
        if (!cntEl) continue;

        cntEl.textContent = count;

        if (cat.total === 0) {
          pctEl.textContent  = '—';
          diffEl.textContent = '—';
          diffEl.className   = 'none';
          continue;
        }

        const ap   = count / cat.total * 100;
        const ep   = spec.weights[rate] / spec.total * 100;
        const diff = ap - ep;
        const abs  = Math.abs(diff);

        pctEl.textContent  = ap.toFixed(1) + '%';
        diffEl.textContent = (diff >= 0 ? '+' : '') + diff.toFixed(1) + '%';
        diffEl.className   = abs < 5 ? 'ok' : abs < 10 ? 'warn' : 'bad';
      }
    }
  }

  // ─── CSV 匯出 ─────────────────────────────────────────────
  function downloadCSV(rows, filename) {
    const lines = rows.map(r =>
      r.map(c => {
        const s = String(c ?? '').replace(/"/g, '""');
        return /[,"\n]/.test(s) ? `"${s}"` : s;
      }).join(',')
    );
    const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function exportStats() {
    const rows = [['類別','倍率','權重','期望%','實際次數','實際%','差值%','狀態']];
    for (const [key, spec] of Object.entries(V2_SPEC)) {
      const cat = state[key];
      for (const rate of spec.rates) {
        const count = cat.counts[rate] || 0;
        const ep = (spec.weights[rate] / spec.total * 100).toFixed(2);
        let ap = '—', diff = '—', status = '—';
        if (cat.total > 0) {
          const a = count / cat.total * 100;
          const d = a - spec.weights[rate] / spec.total * 100;
          ap = a.toFixed(2); diff = (d >= 0 ? '+' : '') + d.toFixed(2);
          status = Math.abs(d) < 5 ? '正常' : Math.abs(d) < 10 ? '留意' : '偏差';
        }
        rows.push([spec.label, `${rate}x`, spec.weights[rate], `${ep}%`, count, cat.total > 0 ? `${ap}%` : '—', cat.total > 0 ? `${diff}%` : '—', status]);
      }
    }
    downloadCSV(rows, `bonus_v2_stats_${Date.now()}.csv`);
  }

  function exportDetail() {
    const rows = [['局號','時間','Single_M2_顏色','Single_M2_倍率','Single_M3_顏色','Single_M3_倍率','AnyDouble_顏色','AnyDouble_倍率','AnyTriple_顏色','AnyTriple_倍率']];
    for (const r of allRounds) {
      rows.push([
        r.round, r.time,
        (r.single_m2||[]).map(i=>i.color).join(';'),
        (r.single_m2||[]).map(i=>i.rate).join(';'),
        (r.single_m3||[]).map(i=>i.color).join(';'),
        (r.single_m3||[]).map(i=>i.rate).join(';'),
        r.any_double?.color ?? '',
        r.any_double?.rate  ?? '',
        r.any_triple?.color ?? '',
        r.any_triple?.rate  ?? ''
      ]);
    }
    downloadCSV(rows, `bonus_v2_detail_${Date.now()}.csv`);
  }

  // ─── 事件綁定 ─────────────────────────────────────────────
  function bindEvents(panel) {
    // 最小化
    let collapsed = false;
    document.getElementById('__bv2Min').addEventListener('click', () => {
      const body = document.getElementById('__bv2Body');
      collapsed = !collapsed;
      body.style.display = collapsed ? 'none' : 'block';
      document.getElementById('__bv2Min').textContent = collapsed ? '＋' : '—';
    });

    // 清空
    document.getElementById('__bv2Clear').addEventListener('click', () => {
      Object.assign(state, {
        totalRounds: 0,
        m2: { total: 0, counts: {} },
        m3: { total: 0, counts: {} },
        ad: { total: 0, counts: {} },
        at: { total: 0, counts: {} }
      });
      allRounds.length = 0;
      processedRounds.clear();
      updatePanel();
    });

    // 匯出
    document.getElementById('__bv2ExStats').addEventListener('click', exportStats);
    document.getElementById('__bv2ExDetail').addEventListener('click', exportDetail);

    // 可拖曳
    let dragging = false, ox = 0, oy = 0;
    document.getElementById('__bv2Hdr').addEventListener('mousedown', e => {
      dragging = true;
      ox = e.clientX - panel.offsetLeft;
      oy = e.clientY - panel.offsetTop;
      e.preventDefault();
    });
    document.addEventListener('mousemove', e => {
      if (!dragging) return;
      panel.style.right = 'auto';
      panel.style.left  = Math.max(0, e.clientX - ox) + 'px';
      panel.style.top   = Math.max(0, e.clientY - oy) + 'px';
    });
    document.addEventListener('mouseup', () => { dragging = false; });

    // 防止面板上的點擊穿透到遊戲
    panel.addEventListener('click', e => e.stopPropagation());
    panel.addEventListener('mousedown', e => e.stopPropagation());
  }

  // ─── 啟動 ─────────────────────────────────────────────────
  createPanel();
  console.log('%c✅ [Bonus V2] 電子骰機率驗證工具已啟動，等待下一局電子開牌...', 'color:#51cf66;font-weight:bold;font-size:13px');
})();
