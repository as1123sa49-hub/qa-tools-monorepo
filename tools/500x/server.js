/**
 * Bonus ColorGame V2 — 電子骰機率驗證工具
 * Express 伺服器 + Playwright WebSocket 攔截
 *
 * 啟動方式：node tools/500x/server.js
 * 瀏覽器開啟：http://localhost:3001
 */

const express = require('express');
const path = require('path');
const { chromium } = require('playwright-core');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// ─── 顏色代碼對照（V2 規格書）────────────────────────────
const COLOR_MAP = {
  801: '黃', 802: '白', 803: '粉', 804: '藍', 805: '紅', 806: '綠'
};

// ─── SSE 客戶端管理 ───────────────────────────────────────
const sseClients = new Set();

function sendSSE(event, data) {
  const msg = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  sseClients.forEach(c => {
    try { c.write(msg); } catch (_) { sseClients.delete(c); }
  });
}

// ─── 解析 d.v[10][143] 電子骰資料 ────────────────────────
function parseBonusData(data143) {
  const result = {
    single_m2: [],   // [{ color, rate }] — Single 2同
    single_m3: [],   // [{ color, rate }] — Single 3同
    any_double: null, // { color, rate } | null
    any_triple: null  // { color, rate } | null
  };

  for (const [key, val] of Object.entries(data143)) {
    const k = Number(key);
    if (k >= 801 && k <= 806) {
      const color = COLOR_MAP[k] || `色${k}`;
      if (val.matchColors === 2) {
        result.single_m2.push({ color, rate: val.rate });
      } else if (val.matchColors === 3) {
        result.single_m3.push({ color, rate: val.rate });
      }
    } else if (k === 807) {
      result.any_double = {
        color: COLOR_MAP[val.bonusColor] || String(val.bonusColor),
        rate: val.rate
      };
    } else if (k === 808) {
      result.any_triple = {
        color: COLOR_MAP[val.bonusColor] || String(val.bonusColor),
        rate: val.rate
      };
    }
  }

  return result;
}

// ─── 收集狀態 ─────────────────────────────────────────────
let browser = null;
let isCollecting = false;
let roundCount = 0;
let targetRounds = 0;

// ─── SSE 端點 ─────────────────────────────────────────────
app.get('/api/events', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  res.write(': heartbeat\n\n');

  const heartbeat = setInterval(() => {
    try { res.write(': heartbeat\n\n'); } catch (_) { clearInterval(heartbeat); }
  }, 15000);

  sseClients.add(res);
  req.on('close', () => {
    clearInterval(heartbeat);
    sseClients.delete(res);
  });
});

// ─── 開始收集 ─────────────────────────────────────────────
app.post('/api/start', async (req, res) => {
  if (isCollecting) {
    return res.json({ ok: false, error: '已在收集中，請先停止' });
  }

  const { url, rounds } = req.body;
  if (!url || !/^https?:\/\//i.test(url)) {
    return res.json({ ok: false, error: '請輸入有效的網址（http / https）' });
  }

  targetRounds = Math.max(1, parseInt(rounds) || 100);
  roundCount = 0;
  isCollecting = true;
  const processedRounds = new Set(); // 去重：記錄已處理的 roundId

  res.json({ ok: true });

  try {
    browser = await chromium.launch({ headless: false });
    const context = await browser.newContext();
    const page = await context.newPage();

    let wsCount = 0;
    page.on('websocket', ws => {
      wsCount++;
      console.log(`[WS #${wsCount}] 偵測到 WebSocket 連線：${ws.url()}`);
      sendSSE('debug', { msg: `偵測到 WebSocket 連線 #${wsCount}：${ws.url()}` });

      ws.on('framereceived', frame => {
        if (!isCollecting) return;
        try {
          let rawPayload = typeof frame.payload === 'string'
            ? frame.payload
            : Buffer.isBuffer(frame.payload)
              ? frame.payload.toString('utf8')
              : String(frame.payload);

          // 去掉 $#|#$ 前綴
          if (rawPayload.startsWith('$#|#$')) {
            rawPayload = rawPayload.slice(5);
          }

          // 略過非 JSON 的 frame
          if (!rawPayload.startsWith('{') && !rawPayload.startsWith('[')) return;

          const data = JSON.parse(rawPayload);

          // 偵錯：記錄所有 notify 事件
          const eventType = data?.d?.v?.[3] || data?.e || '';
          if (eventType) {
            console.log(`[WS frame] e=${data.e} type=${eventType}`);
          }

          if (
            data.e === 'notify' &&
            data.d?.v?.[3] === 'prepareBonusResult'
          ) {
            // 去重：同一局 ID 只處理一次（多條 WS 可能重複推送）
            const roundId = data.d?.v?.[10]?.[0];
            if (roundId && processedRounds.has(roundId)) return;
            if (roundId) processedRounds.add(roundId);

            const data143 = data.d?.v?.[10]?.[143];

            if (data143 && typeof data143 === 'object' && Object.keys(data143).length > 0) {
              roundCount++;
              const parsed = parseBonusData(data143);

              sendSSE('round', {
                round: roundCount,
                time: new Date().toLocaleTimeString('zh-TW', { hour12: false }),
                ...parsed
              });

              sendSSE('status', {
                collecting: true,
                current: roundCount,
                target: targetRounds
              });

              if (roundCount >= targetRounds) {
                doStop(`已完成收集 ${roundCount} 局`);
              }
            }
          }
        } catch (_) { /* 略過無法解析的 frame */ }
      });

      ws.on('close', () => {
        console.log(`[WS #${wsCount}] WebSocket 連線已關閉`);
      });
    });

    sendSSE('status', {
      collecting: true, current: 0, target: targetRounds,
      message: '正在開啟遊戲頁面...'
    });

    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });

    sendSSE('status', {
      collecting: true, current: 0, target: targetRounds,
      message: '頁面已開啟，等待電子骰資料...'
    });

  } catch (err) {
    isCollecting = false;
    sendSSE('error', { message: `啟動失敗：${err.message}` });
    if (browser) {
      try { await browser.close(); } catch (_) {}
      browser = null;
    }
  }
});

// ─── 停止收集 ─────────────────────────────────────────────
async function doStop(reason) {
  if (!isCollecting && !browser) return;
  isCollecting = false;

  sendSSE('status', {
    collecting: false,
    current: roundCount,
    target: targetRounds,
    message: reason || `已停止，共收集 ${roundCount} 局`
  });

  if (browser) {
    try { await browser.close(); } catch (_) {}
    browser = null;
  }
}

app.post('/api/stop', async (req, res) => {
  await doStop();
  res.json({ ok: true });
});

// ─── 未捕獲錯誤（防止靜默退出）────────────────────────────
process.on('uncaughtException', err => {
  console.error('[uncaughtException]', err.message);
});
process.on('unhandledRejection', (reason) => {
  console.error('[unhandledRejection]', reason);
});

// ─── 啟動伺服器 ───────────────────────────────────────────
const PORT = 3001;
const server = app.listen(PORT, () => {
  console.log('\n🎲 Bonus ColorGame V2 電子骰機率驗證工具');
  console.log(`   瀏覽器開啟：http://localhost:${PORT}`);
  console.log('   停止伺服器：Ctrl+C\n');
});

server.on('error', err => {
  if (err.code === 'EADDRINUSE') {
    console.error(`\n❌ Port ${PORT} 已被佔用，請先關閉佔用此 port 的程式後再啟動`);
    console.error('   或修改 server.js 中的 PORT 常數改用其他 port\n');
  } else {
    console.error('❌ 伺服器錯誤：', err.message);
  }
  process.exit(1);
});
