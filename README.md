# bonus-v2-stat-log-checker

本倉庫僅保留兩項工具（與舊版整包 Playwright 專案分離）：

| 路徑 | 說明 |
|------|------|
| `tools/500x/` | 500X V2 電子骰機率驗證（Express + Playwright，見該目錄 `README.md`） |
| `tools/front-log-checker/` | 前端 LOG 攔截腳本 `intercept.js`（貼到目標網站 DevTools Console 執行） |

## 快速開始

### 500x

```bash
npm install
npm run start:500x
```

瀏覽器開啟：<http://localhost:3001>（詳見 `tools/500x/README.md`）。

### front-log-checker

開啟 `tools/front-log-checker/intercept.js`，複製全文到目標頁面的 Console 執行。
