# qa-tools-monorepo

本倉庫為 **QA 工具 monorepo**：以 `tools/` 集中各子工具實作，並以根目錄的 **`tools-hub/`** 作為瀏覽器單一入口（導覽、iframe 嵌入、README 說明；詳見 `tools-hub/README.md`）。

## 目錄一覽

| 路徑 | 說明 |
|------|------|
| `tools-hub/` | QA Tools Hub：側欄切換工具、操作導覽、子服務代理（預設 <http://localhost:3010>） |
| `tools/bonus-v2/` | ColorGame **500X V2** 電子骰局統計與機率驗證（Express + Playwright；預設 <http://localhost:3001>） |
| `tools/front-log-checker/` | **前端行為 LOG 攔截**（XHR）：於目標站 DevTools Console 貼上執行 `intercept.js`，收集／匯出 log |
| `tools/front-log-compare/` | 前端 log **雙檔比對**與**單檔欄位驗證**（靜態頁，可經 Hub 或獨立 `npm start`） |
| `tools/img-compare/` | **圖檔／頁面擷取比對**（獨立服務，Hub 內嵌前需自行啟動） |
| `tools/l10n-text-verify/` | **多語系圖文比對**：上傳 xlsx + 截圖，Gemini OCR 驗證在地化文案 |
| `tools/l10n-capture/` | **多語系擷圖（階段 A）**：上傳 xlsx 選工作表，Playwright 自動擷取遊戲截圖（預設 <http://localhost:3847>） |
| `tools/test-case-generator/` | 測案產生器（靜態工具） |
| `tools/ui-smoke-automation/` | UI smoke 流程腳本與說明 |
| `tools/force-auto-play/` | **Slot 視覺驅動自動下注**（Playwright + EasyOCR + Moondream VLM；FC/JDB/COMBO 單手下注） |

根目錄另有 **`package.json`**：統一安裝測試依賴與常用 npm scripts（Playwright、bonus-v2、smoke 等）。

### force-auto-play（Slot 自動下注）

```bash
cd tools/force-auto-play
python -m venv .venv
.\.venv\Scripts\activate   # Windows
pip install -r requirements.txt
playwright install chromium
ollama pull moondream

pytest tests/test_game_betting.py::test_game_betting_fc --env uat -v
```

詳見 `tools/force-auto-play/README.md`。

## 快速開始

### Bonus V2（500X 機率工具）

```bash
npm install
npm run start:bonus-v2
```

瀏覽器：<http://localhost:3001>（詳見 `tools/bonus-v2/README.md`）。

### front-log-checker（Console 攔截）

開啟 `tools/front-log-checker/intercept.js`，複製全文到目標頁面的 **Console** 執行。

### Tools Hub（整合入口）

```bash
cd tools-hub
npm install
npm start
```

瀏覽器：<http://localhost:3010>。
