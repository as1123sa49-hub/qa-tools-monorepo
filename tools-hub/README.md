# QA Tools Hub

將 `tools/` 下不同工具整合成單一入口頁（本目錄位於**倉庫根目錄**，與 `tools/` 同層），透過分頁切換工具並提供操作導引。

## 目前整合內容

- 圖片比對（`img-compare`）：可 iframe 內嵌（支援 A/B 比對與單站檢視）
- 測案產生器（`test-case-generator`）：可 iframe 內嵌（支援新舊規格比對、匯入Case比對新版）
- 500X 機率統計（`bonus-v2`，目錄 `tools/bonus-v2/`）：可 iframe 內嵌（Hub 代理至 Bonus V2 服務）
- 前端 LOG 驗證（`front-log-checker`）：提供 Console 一鍵複製完整腳本
- LOG 結構比對（`front-log-compare`）：
  - 雙檔比對：上傳舊版 + 新版 JSON（原始），比對 `jsondata` 結構與 `data/root` 欄位
  - 單檔驗證：上傳 1 份 JSON，驗證指定欄位缺失並輸出明細 CSV

## 啟動方式（單一入口）

在**倉庫根目錄**下：

```bash
cd tools-hub
npm install
npm start
```

開啟：`http://localhost:3010`

> `img-compare` 與 `bonus-v2`（500X 服務）仍需先啟動其原始服務：
> - `img-compare`：預設 `http://localhost:3000`
> - `bonus-v2`：預設 `http://localhost:3001`
>
> Hub 會透過路由掛到（頁面／靜態）：
> - `/apps/img-compare/` → 轉發至 img-compare 服務
> - `/apps/bonus-v2/` → 轉發至 bonus-v2（500X）服務
> - `/apps/test-case-generator/` → 本目錄旁 `tools/test-case-generator` 靜態檔
> - `/apps/front-log-compare/` → 本目錄旁 `tools/front-log-compare` 靜態檔
>
> **API 代理（與 iframe 同源有關，請以 `server.js` 為準）：**
> - **Bonus V2** 前端使用絕對路徑 `/api/events`（SSE）、`POST /api/start`、`POST /api/stop`；Hub 將這三條轉到 **`BONUS_500X_URL`**（預設 3001），否則經 Hub 開工具時會誤打到 img-compare。
> - **圖片比對** 的 `/api/session`、`POST /api/capture`、`/api/img/...` 等其餘 **`/api/*`** 轉到 **`IMG_COMPARE_URL`**（預設 3000）。
> - **`GET /api/docs/:tool`**：Hub 內建，回傳各工具 README。
> - **`GET /snippets/front-log-checker.txt`**：Hub 內建，提供攔截腳本內容。
>
> 可用環境變數覆蓋：
> - `PORT`：Hub 入口埠號（預設 `3010`）
> - `IMG_COMPARE_URL`：img-compare 目標位址（預設 `http://127.0.0.1:3000`）
> - `BONUS_500X_URL`：bonus-v2 目標位址（預設 `http://127.0.0.1:3001`）

## 設計原則

- Hub 與既有工具隔離，避免污染既有程式碼。
- 以「單一入口 + 工具路由前綴」整合，降低跨工具衝突。
- 腳本型工具先保留「導引 + 命令」，日後再升級為可嵌入頁面。

## 前端 LOG 驗證（給同事快速使用）

1. 在 Hub 切到「前端 LOG 驗證」。
2. 點「複製」取得 `intercept.js` 完整內容。
3. 到目標站台打開 DevTools Console，直接貼上執行。

Hub 會從 `http://<hub>/snippets/front-log-checker.txt` 讀取最新版攔截腳本內容。
