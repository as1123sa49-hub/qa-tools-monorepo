# Bonus ColorGame V2 — 電子骰機率驗證工具

即時攔截 WebSocket 電子骰資料，比對 V2 規格書期望機率，支援 CSV 匯出。

## 啟動方式

```bash
node tools/500x/server.js
```

瀏覽器開啟：http://localhost:3001

## 使用步驟

1. 填入遊戲網址（含 token，例如 `https://example.com/game?token=xxx`）
2. 填入要收集的局數（預設 100）
3. 點「▶ 開始收集」→ Playwright 自動開啟遊戲頁面並攔截 WebSocket
4. 統計表格即時更新，每局完成就更新一次
5. 達到目標局數後自動停止；或手動點「⏹ 停止」
6. 點「📊 匯出統計 CSV」或「📋 匯出明細 CSV」下載資料

## V2 規格書機率對照

### Single 2同

| 倍率 | 權重 | 期望佔比 |
|------|------|---------|
| 3x   | 64   | 32.00%  |
| 4x   | 64   | 32.00%  |
| 6x   | 39   | 19.50%  |
| 8x   | 22   | 11.00%  |
| 10x  | 11   | 5.50%   |

### Single 3同

| 倍率  | 權重 | 期望佔比 |
|-------|------|---------|
| 10x   | 52   | 26.00%  |
| 20x   | 52   | 26.00%  |
| 30x   | 44   | 22.00%  |
| 60x   | 30   | 15.00%  |
| 100x  | 22   | 11.00%  |

### AnyDouble

| 倍率 | 權重 | 期望佔比 |
|------|------|---------|
| 2x   | 86   | 43.00%  |
| 3x   | 57   | 28.50%  |
| 5x   | 33   | 16.50%  |
| 10x  | 16   | 8.00%   |
| 20x  | 8    | 4.00%   |

### AnyTriple

| 倍率  | 權重 | 期望佔比 |
|-------|------|---------|
| 50x   | 100  | 50.00%  |
| 100x  | 49   | 24.50%  |
| 150x  | 30   | 15.00%  |
| 250x  | 14   | 7.00%   |
| 500x  | 7    | 3.50%   |

## 差值顏色說明

| 顏色 | 範圍 | 意義 |
|------|------|------|
| 🟢 綠色 | < 5%  | 正常 |
| 🟡 黃色 | 5~10% | 留意 |
| 🔴 紅色 | > 10% | 偏差過大 |

## 顏色代碼對照（WebSocket）

| 代碼 | 顏色 |
|------|------|
| 801  | 黃   |
| 802  | 白   |
| 803  | 粉   |
| 804  | 藍   |
| 805  | 紅   |
| 806  | 綠   |
| 807  | AnyDouble |
| 808  | AnyTriple |

## WebSocket 攔截說明

- 攔截事件：`d.v[3] === "prepareBonusResult"`
- 電子骰資料路徑：`d.v[10][143]`
- Single：`{ matchColors: 2|3, rate: N }`
- AnyDouble/Triple：`{ bonusColor: 80X, rate: N }`

## 匯出 CSV 格式

### 統計 CSV（`bonus_v2_stats_*.csv`）

```
類別, 倍率, 權重, 期望%, 實際次數, 實際%, 差值%, 狀態
Single 2同, 3x, 64, 32.00%, 13, 34.21%, +2.21%, 正常
...
```

### 明細 CSV（`bonus_v2_detail_*.csv`）

```
局號, 時間, Single_M2_顏色, Single_M2_倍率, Single_M3_顏色, Single_M3_倍率, AnyDouble_顏色, AnyDouble_倍率, AnyTriple_顏色, AnyTriple_倍率
1, 14:02:01, 黃, 20, , , 黃, 3, 藍, 100
...
```

## 目錄結構

```
tools/500x/
  server.js              ← Express + Playwright 後端
  public/
    index.html           ← 前端頁面
    app.js               ← 前端邏輯
  calculate-expected.js  ← 舊版 CLI 工具（保留）
  check-color-sum.js     ← 舊版 CLI 工具（保留）
  check-stats.js         ← 舊版 CLI 工具（保留）
  verify-rates.js        ← 舊版 CLI 工具（保留）
```
