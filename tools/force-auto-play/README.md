# force-auto-play

視覺驅動的 Slot 遊戲自動化測試框架。結合 **EasyOCR**（文字辨識）與 **Moondream VLM**（視覺語言模型，透過 Ollama 運行），全程不依賴 HTML selector，直接「看畫面」操作遊戲。

---

## 專案結構

```
force-auto-play/
├── conftest.py              # 根層 conftest：設定 sys.path
├── pyproject.toml           # pytest 設定
├── requirements.txt         # 依賴套件清單
├── config/
│   ├── config.yaml          # 環境設定（URL、帳號、entry_mode、大廳錢包 OCR 區域）
│   ├── games.yaml           # 遊戲設定（spin button prompt、搜尋關鍵字等）
│   └── .cache/
│       └── spin_coords.json # 成功點擊座標持久快取（gitignore）
├── core/                    # 核心模組
│   ├── artifact_handler.py  # 截圖與影片歸檔（provider/pass|fail、run 輪次、fail 碼）
│   ├── balance_audit.py     # 房內 footer 餘額 ↔ 大廳錢包交叉驗證
│   ├── comboburst_lobby.py  # COMBO 內部大廳進入遊戲流程
│   ├── fail_codes.py        # 穩定 fail 碼（PRE_BALANCE、SPIN_ACK…）與 run 輪次
│   ├── game_config.py       # GameConfig wrapper（讀取 games.yaml）
│   ├── game_console_listener.py  # 監聽遊戲 console log（含 iframe 多 frame）
│   ├── game_frame_utils.py  # Unity iframe / window.debug 輔助
│   ├── game_utils.py        # 共用工具（navigate、spin、layout、provider chip）
│   ├── hybrid_locator.py    # VLM + OCR 混合定位器
│   ├── layout_detect.py     # 直橫版自動偵測（canvas + footer OCR）
│   ├── reel_motion.py       # 轉輪區 motion assist（spin ack / retry 判斷）
│   ├── run_evidence.py      # pass/fail 證明 JSON（run_evidence.json）
│   ├── spin_coord_cache.py  # Spin 座標持久快取讀寫
│   ├── ui_locator.py        # EasyOCR UI 掃描（登入、搜尋、遊戲標籤）
│   ├── video_auditor.py     # 錄影視覺品質審查
│   ├── vision_client.py     # Ollama Moondream VLM client
│   └── visual_auditor.py    # 即時截圖視覺品質審查（黑屏、破圖偵測）
├── scripts/
│   └── run_fc_jdb_full_with_rerun.ps1  # FC+JDB 全量 → --lf 重跑 fail
├── tests/
│   ├── conftest.py          # 所有 pytest fixtures
│   ├── test_game_betting.py       # 單手下注測試
│   └── test_game_continuous_bet.py  # 連續下注測試（預設 10 輪）
├── tools/
│   ├── clean_and_open_allure.py  # Allure 報告工具
│   ├── generate_games_yaml.py    # 從 list API 同步 games.yaml
│   ├── verify_games_yaml.py      # 比對 games.yaml 與 list API
│   └── verify_jc_games.py        # 比對 pre-approved 試算表與 list API
├── test_artifacts/          # 測試截圖歸檔（自動產生，見下方「測試產物」）
├── logs/                    # pytest session log（pytest_YYYYMMDD_HHMMSS.log）
├── recordings/              # （legacy）舊版錄影路徑
└── allure-results/          # Allure 原始結果（自動產生）
```

---

## 環境需求

- Python 3.12+（建議 3.12；3.13 亦可）
- [Ollama](https://ollama.com/)（需在本機運行，port 11434）
- Ollama 模型：`moondream`

```bash
# 確認 Ollama 已啟動並載入模型
ollama pull moondream
ollama serve
```

---

## 安裝

```bash
cd force-auto-play

# Windows
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

---

## 設定

### `config/config.yaml`

填入測試環境的 URL、帳號，以及進入大廳的方式（`entry_mode`）：

| `entry_mode` | 說明 |
|---|---|
| `jc_lobby` | JC 平台大廳（`jackpot-uat.combo.ph`），登入後搜尋進遊戲 |
| `comboburst_portal` | COMBO 內部大廳（`games-dev.comboburst.com`），切 UAT + 英文後搜尋進遊戲 |

COMBO UAT 範例（含大廳錢包 OCR 區域，供結算後交叉驗證）：

```yaml
projects:
  client:
    environments:
      uat:
        web_url: "https://jackpot-uat.combo.ph/"
        entry_mode: comboburst_portal
        # JC 大廳：右上 header pill + 左側 Balance 卡片
        jc_lobby_wallet_regions:
          - { x_start: 0.80, x_end: 0.99, y_start: 0.02, y_end: 0.12 }
          - { x_start: 0.02, x_end: 0.24, y_start: 0.13, y_end: 0.32 }
        jc_lobby_wallet_refresh_regions:
          - { x_start: 0.855, x_end: 0.895, y_start: 0.038, y_end: 0.088 }  # header ↻
          - { x_start: 0.185, x_end: 0.235, y_start: 0.188, y_end: 0.248 }  # sidebar ↻
        comboburst:
          lobby_url: "https://games-dev.comboburst.com/home/index.html"
          portal_env: COMBO_UAT
          game_host: "games-uat.comboburst.com"
          auth_file: "config/.auth/comboburst_lobby.json"
          viewport: { width: 1920, height: 911 }
          # COMBO portal：右上 wallet bar（例：3,335,538.45 PHP）
          # 金額 OCR 區（不含右側 ↻）
          lobby_wallet_region:
            x_start: 0.66
            x_end: 0.90
            y_start: 0.0
            y_end: 0.10
          lobby_wallet_refresh_region:
            x_start: 0.895
            x_end: 0.928
            y_start: 0.018
            y_end: 0.072
          lobby_wallet_refresh_region:
            x_start: 0.895
            x_end: 0.928
            y_start: 0.018
            y_end: 0.072
          portal_chrome_exclusion:
            y_start: 0.87   # 底部直橫版切換列，Spin 點擊會避開
        accounts:
          player_vision:
            username: "your_username"
            password: "your_password"
```

COMBO portal 需先儲存登入狀態：

```bash
.\.venv\Scripts\python.exe tools\save_comboburst_auth.py
```

### `config/games.yaml`
新增遊戲時，照現有格式加入 `games` 區塊，描述 spin button 的視覺特徵與搜尋關鍵字即可。直橫版預設為 `auto`（由 `layout_detect.py` 自動判斷），無需在 yaml 手動標 `layout: portrait`。

---

## COMBO 單手下注測試（`test_game_betting_combo`）

COMBO 遊戲使用 `settlement_mode="console"`，流程如下：

```
進大廳 → 記錄 B0_lobby（大廳錢包 OCR）
  → 進遊戲 → 自動判斷直橫版
  → spin 前讀 footer 主餘額（before_primary）
  → VLM 偵測 Spin + 多點點擊（或快取座標）
  → 結算判定（console 優先，visual 備援）
  → 回大廳 → B1_lobby 與房內 B1 交叉驗證
```

### Spin 點擊策略

1. **持久快取** `config/.cache/spin_coords.json`（成功後記住座標）
2. **VLM grid region** 偵測 Spin bbox
3. **直版 + loose bbox**（框到 Spin+Auto+Turbo 整條）：**snap** 到 `PORTRAIT_COMBO_SPIN_REGION` 底部中央錨點，再上下左右偏移掃描
4. **portal 底列排除**：y ≥ 0.87 的座標不點（直橫版切換列）；落在該區的 stale cache 會自動清除

### 結算判定（避免假 PASS）

| 層級 | 條件 |
|------|------|
| **首選** | `game_console_listener`：`Spin response` / `ReciviedSpinResponse` / 餘額公式 `B1 = B0 - Bet + Win` |
| **備援** | footer **主餘額**變化 ≥ 一注（非整圖任意數字比對） |
| **最後保險** | `balance_audit`：回大廳後**點擊 ↻ 刷新錢包**，輪詢直到房內 B1 ≈ 大廳錢包 B1 |

Console 監聽掛在 **page + 所有 iframe**；進遊戲後會對 game frame 執行 `window.debug = true`。

### 清除 Spin 座標快取

快取座標錯誤（例如點到 portal 底列）時，手動清除後重跑：

```powershell
# 清除單一遊戲
.\.venv\Scripts\python.exe -c "from core.spin_coord_cache import clear_spin_coord; clear_spin_coord('CMB_COMBO_GoldenBass')"

# 清除全部
Remove-Item config\.cache\spin_coords.json -ErrorAction SilentlyContinue
```

測試中若 cache 點擊後 spin 未觸發，也會自動清除並改走 VLM 重偵測。

---

## FC / JDB 單手下注測試（JC 大廳，`test_game_betting_fc` / `_jdb`）

FC、JDB 使用 **visual settlement**（非 COMBO console），流程如下：

```
進 JC 大廳 → 記錄 B0_lobby
  → 搜尋進遊戲（多結果時先點第二排供應商 chip：FA CHAI / JDB）
  → 讀 footer 主餘額（before_primary；讀不到且側欄開 → 收合紫 tab 再 OCR）
  → VLM 偵測 Spin + 點擊（ack 失敗且 balance/reels 皆未變 → 最多再點 1 次）
  → 結算（footer delta / 公式；B1 雙次確認）
  → 回大廳 → 房內 B1 與大廳 B1 交叉驗證
```

### JC 大廠商搜尋

搜尋結果 **≥ 2 張遊戲卡** 時，會先 OCR 點擊第二排 **供應商 chip**（例如 FC → FA CHAI、JDB → JDB），再點目標遊戲海報，避免 Zeus / Gold Rush 等同名誤點。

### Spin ack 與條件式 retry

| 步驟 | 說明 |
|------|------|
| 第一次 click | 等 ack 視窗（FC/JDB portrait 約 14s + 3s grace） |
| Late confirm | ack 逾時後再讀 footer 數次（只讀不點） |
| **Retry click** | 僅當 **balance 仍 ≈ before** 且 **reels = static**（JDB reel assist）時，同一座標最多再點 1 次 |
| 打平但已轉 | reels 有動 → **不** retry，避免雙 spin |

可在 `games.yaml` 單款設 `spin_click_retry: false` 關閉 retry。

### 失敗碼（pytest 訊息與 artifact 資料夾）

| 碼 | 典型原因 |
|----|----------|
| `ENTRY_NETWORK` | 進場 network error |
| `ENTRY_UNKNOWN` | 進場失敗（載入、搜尋等） |
| `PRE_BALANCE` | spin 前讀不到 footer 主餘額 |
| `SPIN_ACK` | 點了 spin 但 ack / balance 皆未變 |
| `SPIN_NETWORK` | spin 中等 network anomalies；**跳過** lobby audit |
| `SETTLE` / `SETTLE_TIMEOUT` | 結算公式或逾時 |
| `AUDIT` | 大廳 wallet 交叉驗證失敗 |

訊息格式：`[PRE_BALANCE] … | lobby_b0=… | before=…`（含一行數字摘要）。

### 全量 + 重跑 fail（Windows）

```powershell
# 若 ExecutionPolicy 擋住 .ps1：
powershell -ExecutionPolicy Bypass -File .\scripts\run_fc_jdb_full_with_rerun.ps1

# 第一輪設 FORCE_AUTO_PLAY_RUN=1，--lf 重跑設 =2（腳本已處理）
```

手動兩輪（與腳本等效）：

```powershell
$env:FORCE_AUTO_PLAY_RUN = "1"
.\.venv\Scripts\python.exe -m pytest `
  tests/test_game_betting.py::test_game_betting_fc `
  tests/test_game_betting.py::test_game_betting_jdb `
  --env uat -v

$env:FORCE_AUTO_PLAY_RUN = "2"
.\.venv\Scripts\python.exe -m pytest `
  tests/test_game_betting.py::test_game_betting_fc `
  tests/test_game_betting.py::test_game_betting_jdb `
  --env uat -v --lf
```

---

## 執行測試

### pytest node id 與 `-k` 篩選

parametrize 使用 **`ids=_game_display_name`**，node id 為**遊戲顯示名稱**，不是 `FC-SLOT-004`：

```text
test_game_betting_fc[chromium-Night Market]
test_game_betting_jdb[chromium-Piggy Bank]
```

- **不要用** `-k "JDB-SLOT-123"`（會 0 selected）
- 用 **完整 node** 或 `-k` 拆字：`Piggy and Bank`
- 遊戲名含空格時，`-k` 不能寫 `Piggy Bank`，需 `Piggy and Bank`

先確認 node 名稱：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_game_betting.py --collect-only -q -k "Piggy"
```

### Smoke（4 款，修完後快速驗證）

```powershell
$env:FORCE_AUTO_PLAY_RUN = "1"
.\.venv\Scripts\python.exe -m pytest `
  "tests/test_game_betting.py::test_game_betting_jdb[chromium-Piggy Bank]" `
  "tests/test_game_betting.py::test_game_betting_fc[chromium-Pong Pong Hu]" `
  "tests/test_game_betting.py::test_game_betting_fc[chromium-Chinese New Year]" `
  "tests/test_game_betting.py::test_game_betting_fc[chromium-Night Market]" `
  --env uat -v
```

若 collect 顯示無 `chromium-` 前綴，去掉即可。

### 常用指令

```powershell
cd force-auto-play
# Windows 請先 .\.venv\Scripts\activate

# COMBO 單手下注（UAT comboburst portal，console 結算）
pytest tests/test_game_betting.py::test_game_betting_combo --env uat -v

# FC / JDB 全量 slot
pytest tests/test_game_betting.py::test_game_betting_fc tests/test_game_betting.py::test_game_betting_jdb --env uat -v

# 依遊戲名篩選（COMBO 範例）
pytest tests/test_game_betting.py::test_game_betting_combo -k "Prosperous and Tiger" --env uat -v

# 有頭模式
pytest tests/test_game_betting.py::test_game_betting_fc -k "Night and Market" --env uat -v --headed

# 連續下注（預設 10 輪）
pytest tests/test_game_continuous_bet.py -k "Prosperous and Tiger" -v

# 關閉錄影：config/config.yaml 設定 record_video: false
```

```bash
# macOS / Linux
source .venv/bin/activate
pytest tests/test_game_betting.py::test_game_betting_fc --env uat -v
```

---

## Allure 報告

```bash
# 跑完測試後，生成並啟動報告 server
python tools/clean_and_open_allure.py report

# 清理所有報告與截圖
python tools/clean_and_open_allure.py clean
```

瀏覽器開啟 `http://127.0.0.1:50000` 即可查看報告。

---

## JC 遊戲清單驗證（`verify_jc_games.py`）

比對 **pre-approved gamelist 試算表**（工作頁 XLSX）與 JC 平台 **`POST /api/fe/v3/game/list`** 回應，確認新增遊戲是否已上架、名稱與類型是否一致。可選擇模擬前台以英文名搜尋。

### 試算表欄位對應

| 試算表欄 | 用途 |
|----------|------|
| G — GAME CODE | 主要比對鍵（如 `FC-SLOT-037` → API `SANA_FC_FC-SLOT-037`） |
| H — GAME NAME | 英文名稱交叉驗證 |
| D — GAME CONTENT PROVIDER | 廠商（如 `FA CHAI (FC)` → `FC`） |
| L — STG GAME TYPE | 遊戲類型（`SLOT` / `EGAME` / `FH` 等，與 API `game_type` 對應） |
| U — Support for the STG | 測試環境支援度（`Y` / 空白） |

腳本會自動偵測標題列；若偵測失敗，則使用上述欄位位置作為 fallback。多工作表 xlsx 預設會驗證所有頁籤，並跳過以 `1 ` 開頭的舊版頁籤（如 `1 Pragmatic Play`）。

### 基本用法

```bash
# 驗證單一廠商工作表（UAT）
python tools/verify_jc_games.py \
  --xlsx path/to/gamelist.xlsx \
  --sheet "FA CHAI0626" \
  --provider FC

# 含前台搜尋模擬（以英文名子字串比對 game_name）
python tools/verify_jc_games.py \
  --xlsx path/to/gamelist.xlsx \
  --sheet "FA CHAI0626" \
  --provider FC \
  --check-search

# 只驗 STG 支援度 = Y 的遊戲（U 欄）
python tools/verify_jc_games.py \
  --xlsx path/to/gamelist.xlsx \
  --sheet "FA CHAI0626" \
  --provider FC \
  --stg-only \
  --check-search

# 驗證整份 xlsx 所有廠商
python tools/verify_jc_games.py --xlsx path/to/gamelist.xlsx --env uat

# 輸出 JSON 詳細報告
python tools/verify_jc_games.py \
  --xlsx path/to/gamelist.xlsx \
  --sheet "FA CHAI0626" \
  --output-json result_fc.json
```

### 參數說明

| 參數 | 說明 |
|------|------|
| `--xlsx` | pre-approved gamelist `.xlsx` 路徑（必填） |
| `--env` | API 環境：`uat`（預設）或 `pp` |
| `--sheet` | 只驗指定工作表，可重複指定（支援部分名稱比對） |
| `--provider` | 只驗指定廠商 ID（如 `FC`、`PP`、`PG`） |
| `--stg-only` | 只驗 U 欄 STG 支援度 = `Y` 的列；不加則驗工作表內全部遊戲 |
| `--check-search` | 額外模擬前台搜尋（不分大小寫子字串） |
| `--output-json` | 將每筆結果寫入 JSON 檔 |

### 驗證邏輯

1. 讀取試算表 → 建立期望清單
2. 呼叫 list API → 建立平台實際清單
3. 以 **GAME CODE** 為主鍵比對；找不到時以英文名備援
4. 檢查廠商、類型、英文名、API `status` 是否為上架（`1`）
5. （可選）以英文名模擬前台搜尋是否可找到該遊戲

### 輸出與結束碼

- 終端機依工作表分組顯示 `[OK]` / `[WARN]` / `[FAIL]`
- 全部通過 → `exit 0`；有任何缺漏或差異 → `exit 1`（可用於 CI）

### 相關工具

| 腳本 | 用途 |
|------|------|
| `tools/verify_games_yaml.py` | 比對 `config/games.yaml` 與 list API |
| `tools/generate_games_yaml.py` | 從 list API 同步產生 `games.yaml` |

依賴 `openpyxl`（已列入 `requirements.txt`）。

---

## 新增遊戲

1. 在 `config/games.yaml` 新增遊戲設定（含 `provider`、`spin_button` 描述等）
2. 在 `tests/test_game_betting.py` 對應的 `@pytest.mark.parametrize("game_id", [...])` 加入 game_id（FC → `test_game_betting_fc`，JDB → `test_game_betting_jdb`，COMBO → `test_game_betting_combo`）

不需要修改核心流程程式碼；可選在單款設 `spin_click_retry: false` 關閉 spin retry。

---

## 測試產物

每次測試結束後，`ArtifactHandler` 會將 session 資料夾歸檔至：

```text
test_artifacts/{FC|JDB|COMBO}/{pass|fail}/{timestamp}_{gameId}_{GameName}[_runN][_FAILCODE]/
```

| 後綴 | 說明 |
|------|------|
| `_run1` | 第一輪全量（`FORCE_AUTO_PLAY_RUN=1` 或腳本第一輪） |
| `_run2` | `--lf` 重跑 fail（`FORCE_AUTO_PLAY_RUN=2`） |
| `_SPIN_ACK` 等 | fail 時的穩定 fail 碼（見上方 FC/JDB 章節） |

**pass 與 fail 都會寫** `run_evidence.json`（餘額、spin 結算、`spin_click.retry_used` 等），便於對照 pytest 訊息一行摘要。

| 子目錄 / 檔案 | 內容 |
|---------------|------|
| `setup/` | 搜尋、進入遊戲階段截圖 |
| `gameplay/` | 正常流程截圖（含 `success_settlement`、`audit_lobby_wallet`） |
| `failures/` | 失敗時的截圖證據 |
| `debug/` | OCR 裁切、Spin 偵測中間產物 |
| `recordings/` | 錄影檔（`.webm`） |
| `run_evidence.json` | 輕量 JSON 證明（pass/fail 皆有） |

Session log 另寫入 `logs/pytest_YYYYMMDD_HHMMSS.log`。

---

## 備案：當 Vision 方案無法實現自主探索

純視覺方案（VLM + OCR）在自主探索場景下可能遇到以下瓶頸：

- **VLM 幻覺（Hallucination）**：模型對 Canvas 內的動態元素產生錯誤座標，導致連續點擊失敗
- **推理延遲過高**：本地 Moondream 每次推理 2-5 秒，無法即時跟上遊戲狀態變化（如快速轉場、彈窗連發）
- **狀態判斷不穩定**：VLM 對「轉輪轉動中」vs「轉輪停止」的判斷缺乏一致性，造成 Spin 時機誤判
- **複雜 UI 場景崩潰**：多層彈窗、特效疊加時，模型無法正確辨識可操作元素

### 降級方案一：Console Log 驅動（已具備基礎）

現有的 `game_console_listener.py` 已能監聽遊戲內部事件（餘額變動、FG 觸發、GameMode 切換）。若 Vision 不可靠，可將其提升為**主要狀態機引擎**：

| 原本（Vision 驅動） | 降級後（Console 驅動） |
|---|---|
| VLM 判斷轉輪是否停止 | 監聽 `spinEnd` / `roundComplete` 事件 |
| OCR 讀取餘額數字 | 直接從 console log 解析 `balance` 數值 |
| VLM 偵測 Free Game 彈窗 | 監聽 `gameMode: freeGame` 狀態變更 |

**操作層**仍使用視覺定位點擊 Spin 按鈕（此為最穩定的單一元素偵測），但**狀態判斷與流程控制**全部交由 Console Log。這樣即使 VLM 無法自主探索複雜狀態，也能透過遊戲自身的事件流驅動測試。

### 降級方案二：固定座標 + Template Matching（去 VLM 化）

若 VLM 整體不穩定，可完全移除 VLM 依賴，改用傳統 CV：

```
# 每款遊戲預先錄製一組 UI 模板（Template）
config/templates/
├── prosperous_tiger/
│   ├── spin_button_idle.png
│   ├── spin_button_spinning.png
│   └── free_game_popup.png
└── ...
```

- 使用 OpenCV `matchTemplate` 進行按鈕定位，無推理延遲
- 用 SSIM（結構相似度）比對畫面狀態，判斷轉輪是否停止
- 按鈕座標在首次定位後快取，後續直接複用

**代價**：每新增一款遊戲需手動截取模板圖片，喪失「零配置新增遊戲」的優勢。但穩定性可達 99%+。

### 降級方案三：混合架構（推薦的務實路線）

不追求 VLM 做到「完全自主探索」，而是將其限縮為**輔助角色**：

```
操作決策層：Console Log 事件 → 決定「何時做」
元素定位層：Template Matching → 決定「點哪裡」（穩定路徑）
            VLM → 僅在模板匹配失敗時啟用（Fallback）
狀態審計層：OCR + Console Log 交叉驗證 → 確認結果正確
            balance_audit → 房內 footer 餘額 vs 大廳錢包（最後保險）
```

此方案的核心思想是：**不讓 VLM 做決策者，只讓它做最後的兜底**。日常測試走快速且穩定的 Console + Template 路線；僅在遇到未知 UI（新版本改版、未見過的彈窗）時才啟用 VLM 嘗試探索。

> **已實作**：`balance_audit.py` 提供 JC / COMBO 大廳錢包 OCR、`pick_primary_balance`（footer 主餘額）、`audit_cross_venue_wallet`（跨場驗證），並整合進 `test_game_betting.py`。

### 降級方案四：操作現有 Unity Debug Console（零開發依賴，立即可行）

**現況**：DEV / UAT 環境的遊戲已內建 Debug 工具，支援指定盤面（Reel Strip）和觸發 Feature Game 等指令。只是進入方式與操作流程較為繁瑣（需要特定手勢或按鍵組合開啟 Debug Console，手動輸入指令，再關閉介面）。

**核心想法**：既然 Unity 已經支援這些 Debug 指令，我們不需要等開發注入新 Hook——直接用 Playwright 模擬操作現有的 Debug Console 即可。

#### 操作流程

```
1. 開啟 Debug Console（座標點擊 / 鍵盤快捷鍵 / 特殊手勢）
2. 在輸入框輸入 Debug 指令
3. 關閉 Debug Console
4. 點擊 Spin → 遊戲按照指定盤面/Feature 執行
5. 驗證結果
```

#### Python 實作範例

```python
# core/debug_console.py
class DebugConsole:
    """操作 Unity 內建 Debug Console 的封裝"""

    def __init__(self, page, config: dict):
        self.page = page
        # Debug Console 的開啟/關閉方式與輸入框位置（每個專案可能不同）
        self.open_method = config.get("open_method", "keyboard")  # keyboard / gesture / coordinate
        self.open_key = config.get("open_key", "`")               # 預設反引號鍵
        self.open_coords = config.get("open_coords", None)        # 座標點擊方式
        self.input_coords = config.get("input_coords", None)      # 輸入框座標
        self.close_key = config.get("close_key", "`")

    async def open(self):
        """開啟 Debug Console"""
        if self.open_method == "keyboard":
            await self.page.keyboard.press(self.open_key)
        elif self.open_method == "coordinate":
            # 某些遊戲需要點特定區域（如連點左上角 5 次）
            for _ in range(self.open_coords.get("tap_count", 1)):
                await self.page.click(f"canvas", position={
                    "x": self.open_coords["x"],
                    "y": self.open_coords["y"]
                })
                await self.page.wait_for_timeout(100)
        await self.page.wait_for_timeout(500)  # 等 Console 動畫完成

    async def close(self):
        """關閉 Debug Console"""
        await self.page.keyboard.press(self.close_key)
        await self.page.wait_for_timeout(500)

    async def execute(self, command: str):
        """開啟 Console → 輸入指令 → 關閉 Console"""
        await self.open()

        if self.input_coords:
            # 點擊輸入框取得焦點
            await self.page.click("canvas", position={
                "x": self.input_coords["x"],
                "y": self.input_coords["y"]
            })

        # 清空並輸入指令
        await self.page.keyboard.press("Control+a")
        await self.page.keyboard.type(command, delay=30)
        await self.page.keyboard.press("Enter")
        await self.page.wait_for_timeout(300)

        await self.close()

    # ── 常用 Debug 指令封裝 ──

    async def set_reel_strip(self, strip_id: str):
        """指定下一輪的盤面結果"""
        await self.execute(f"set_strip {strip_id}")

    async def trigger_feature_game(self, feature: str = "free_game"):
        """強制觸發 Feature Game"""
        await self.execute(f"trigger {feature}")

    async def set_balance(self, amount: int):
        """設定測試餘額"""
        await self.execute(f"set_balance {amount}")

    async def force_win(self, symbol: str, count: int = 5):
        """指定中獎符號與數量"""
        await self.execute(f"force_win {symbol} {count}")
```

#### 在 games.yaml 中加入 Debug Console 設定

```yaml
games:
  prosperous_tiger:
    # ... 現有設定 ...
    debug_console:
      open_method: "coordinate"        # keyboard / coordinate / gesture
      open_coords: { x: 15, y: 15, tap_count: 5 }  # 連點左上角 5 次
      input_coords: { x: 400, y: 500 }  # Console 輸入框位置
      close_key: "Escape"
      commands:
        trigger_fg: "trigger free_game"
        set_strip: "set_strip {strip_id}"
        force_scatter: "force_win SCATTER 3"
```

#### 測試場景範例

```python
# tests/test_game_debug_commands.py
@pytest.mark.parametrize("game_id", ["prosperous_tiger"])
async def test_force_trigger_free_game(page, game_id, debug_console):
    """用 Debug 指令強制觸發 Free Game，驗證 FG 流程正確性"""
    # 1. 進入遊戲（現有流程）
    await navigate_to_game(page, game_id)

    # 2. 用 Debug Console 強制觸發 FG
    await debug_console.trigger_feature_game("free_game")

    # 3. 點 Spin — 這一輪會進入 Free Game
    await click_spin(page)

    # 4. 驗證：Console Log 應出現 gameMode: freeGame
    events = await console_listener.wait_for_event("gameModeChanged", timeout=15)
    assert events["mode"] == "freeGame"

@pytest.mark.parametrize("strip_id,expected_win", [
    ("strip_all_wild", True),
    ("strip_no_win", False),
])
async def test_specific_reel_result(page, debug_console, strip_id, expected_win):
    """指定盤面驗證賠率計算是否正確"""
    await debug_console.set_reel_strip(strip_id)
    await click_spin(page)
    result = await console_listener.wait_for_event("spinEnd", timeout=15)
    assert (result["win"] > 0) == expected_win
```

#### 此方案的關鍵優勢

- **零開發依賴**：利用 DEV/UAT 已有的 Debug 工具，不需要開發改任何程式碼
- **立即可用**：只要調查清楚 Debug Console 的開啟方式與指令格式即可動工
- **精準控制測試場景**：可指定盤面、觸發 Feature Game、設定餘額，不再靠隨機
- **大幅提升測試覆蓋率**：能有目的地測試特定中獎組合、邊界條件、罕見的 Feature 觸發
- **與 Vision 測試互補**：Vision 負責探索性測試（隨機打），Debug Console 負責確定性測試（指定結果驗證）

#### 需先調查確認的事項

| 項目 | 說明 |
|------|------|
| Debug Console 開啟方式 | 確認每款遊戲的開啟手勢/按鍵（可能不統一） |
| 支援的指令清單 | 向開發索取或自行實驗，整理出所有可用的 Debug 指令 |
| 指令格式與參數 | 例如 `set_strip` 的參數是 strip ID 還是符號陣列 |
| Console UI 元素座標 | 在不同解析度下，輸入框與按鈕的座標是否穩定 |
| 環境限制 | 確認 Staging / Production 是否已移除 Debug Console |

### 降級方案五：Unity Debug Bridge（需開發協助，長期方案）

如果純外部觀測（Vision / Console Log）都不夠可靠，最根本的解法是**從遊戲內部注入 Debug Hook**，讓 Unity 主動暴露狀態給測試框架。這需要開發團隊配合，或取得遊戲 Repo 進行實驗。

#### 核心概念

在 Unity WebGL Build 中注入一層輕量的 Debug Bridge，透過 `jslib` plugin 將遊戲內部狀態推送到瀏覽器的 `window` 物件，讓 Playwright 可直接讀取：

```
┌─────────────────────────────────────────────┐
│  Unity Runtime (C#)                         │
│  ┌───────────────────────────┐              │
│  │ QADebugBridge.cs          │              │
│  │  - OnSpinStart()          │              │
│  │  - OnSpinEnd(result)      │              │
│  │  - OnBalanceChanged(val)  │              │
│  │  - OnGameModeChanged(mode)│              │
│  │  - GetClickableElements() │              │
│  └────────────┬──────────────┘              │
│               │ jslib interop               │
│  ┌────────────▼──────────────┐              │
│  │ qa_bridge.jslib            │              │
│  │  window.__QA_STATE__ = {} │              │
│  │  window.__QA_EVENTS__ = []│              │
│  └───────────────────────────┘              │
└─────────────────────────────────────────────┘
        │  Playwright page.evaluate()
        ▼
┌─────────────────────────────────────────────┐
│  force-auto-play (Python)                   │
│  core/unity_debug_bridge.py                 │
│  - await page.evaluate("window.__QA_STATE__")│
│  - 精確取得 game state、餘額、可點擊座標     │
└─────────────────────────────────────────────┘
```

#### Unity 端需要的最小改動

**1. C# Debug Bridge 腳本（開發提供或我們實驗注入）**

```csharp
// QADebugBridge.cs — 掛在場景的空 GameObject 上
// 僅在 DEBUG / QA Build 中編譯
#if QA_BUILD || UNITY_EDITOR
using System.Runtime.InteropServices;
using UnityEngine;

public class QADebugBridge : MonoBehaviour
{
    [DllImport("__Internal")]
    private static extern void QA_PushState(string json);

    [DllImport("__Internal")]
    private static extern void QA_PushEvent(string json);

    public void OnSpinEnd(SpinResult result)
    {
        QA_PushEvent(JsonUtility.ToJson(new {
            type = "spinEnd",
            symbols = result.symbols,
            win = result.winAmount,
            timestamp = Time.time
        }));
    }

    public void OnBalanceChanged(decimal balance)
    {
        QA_PushState(JsonUtility.ToJson(new {
            balance = balance,
            gameMode = GameManager.Instance.CurrentMode.ToString(),
            isSpinning = GameManager.Instance.IsSpinning,
            freeSpinsLeft = GameManager.Instance.FreeSpinsRemaining
        }));
    }

    // 暴露可點擊元素的螢幕座標
    public void ExposeClickTargets()
    {
        var targets = FindObjectsOfType<ClickableUI>();
        var coords = targets.Select(t => new {
            name = t.gameObject.name,
            screenPos = Camera.main.WorldToScreenPoint(t.transform.position),
            enabled = t.interactable
        });
        QA_PushState(JsonUtility.ToJson(new { clickTargets = coords }));
    }
}
#endif
```

**2. jslib Plugin（WebGL 端的橋接）**

```javascript
// qa_bridge.jslib — 放在 Assets/Plugins/WebGL/
mergeInto(LibraryManager.library, {
    QA_PushState: function(jsonPtr) {
        var json = UTF8ToString(jsonPtr);
        window.__QA_STATE__ = JSON.parse(json);
    },
    QA_PushEvent: function(jsonPtr) {
        var json = UTF8ToString(jsonPtr);
        window.__QA_EVENTS__ = window.__QA_EVENTS__ || [];
        window.__QA_EVENTS__.push(JSON.parse(json));
        // 僅保留最近 200 筆，避免記憶體爆炸
        if (window.__QA_EVENTS__.length > 200) {
            window.__QA_EVENTS__ = window.__QA_EVENTS__.slice(-100);
        }
    }
});
```

#### Python 端讀取方式

```python
# core/unity_debug_bridge.py
class UnityDebugBridge:
    def __init__(self, page):
        self.page = page

    async def get_state(self) -> dict:
        return await self.page.evaluate("window.__QA_STATE__ || {}")

    async def pop_events(self, event_type: str = None) -> list:
        js = """() => {
            const events = window.__QA_EVENTS__ || [];
            window.__QA_EVENTS__ = [];
            return events;
        }"""
        events = await self.page.evaluate(js)
        if event_type:
            return [e for e in events if e.get("type") == event_type]
        return events

    async def wait_for_event(self, event_type: str, timeout: float = 30):
        """等待特定遊戲事件，取代 VLM 狀態判斷"""
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            events = await self.pop_events(event_type)
            if events:
                return events[-1]
            await asyncio.sleep(0.1)
        raise TimeoutError(f"等待 {event_type} 超時 ({timeout}s)")

    async def get_click_targets(self) -> list:
        """直接拿 Unity 暴露的可點擊座標，零 VLM 推理"""
        state = await self.get_state()
        return state.get("clickTargets", [])
```

#### 與現有架構的整合方式

不需要大改現有框架，只需在 `game_utils.py` 加一層判斷：

```python
# 偵測是否有 Debug Bridge 可用
has_bridge = await page.evaluate("typeof window.__QA_STATE__ !== 'undefined'")

if has_bridge:
    # 精確路線：直接讀取 Unity 內部狀態
    state = await bridge.get_state()
    is_spinning = state["isSpinning"]
    balance = state["balance"]
else:
    # 退回原本的 Vision / Console Log 路線
    is_spinning = await vlm_detect_spinning(page)
    balance = await ocr_read_balance(page)
```

#### 需要跟開發團隊協商的事項

| 項目 | 說明 | 優先級 |
|------|------|--------|
| **QA Build Flag** | 在 CI Pipeline 加一個 `QA_BUILD` 的 Scripting Define Symbol，僅 QA 環境包含 Debug Bridge | 高 |
| **提供 Repo 實驗權限** | 讓 QA 團隊 fork 一份遊戲 repo，自行在非正式分支注入 `QADebugBridge.cs` 做 PoC | 高 |
| **事件規格對齊** | 統一 `spinEnd`、`balanceChanged`、`gameModeChanged` 等事件名稱與 payload 格式 | 中 |
| **座標系轉換** | Unity Screen Space → WebGL Canvas CSS pixel 的座標轉換公式確認 | 中 |
| **Release Build 安全** | 確認 `#if QA_BUILD` 條件編譯生效，正式版不包含任何 Debug 接口 | 高 |

#### 此方案的優勢

- **零推理延遲**：狀態讀取走 `page.evaluate()`，< 1ms 回傳
- **100% 精確**：餘額、遊戲狀態、可點擊座標都是遊戲引擎的真值（Ground Truth）
- **可完全自主探索**：知道哪些元素可點、當前什麼狀態，代理人可建立完整的狀態機
- **與 Vision 互補**：Vision 用來做「視覺品質審計」（破圖、動畫異常），Debug Bridge 負責「狀態與操作」

### 切換時機判斷

| 指標 | 閾值 | 動作 |
|------|------|------|
| VLM Spin 偵測成功率 | < 85%（連續 50 輪） | 自動切換至 Template Matching |
| 單輪 VLM 推理耗時 | > 8 秒 | 降級至 Console Log 驅動 |
| 連續 3 輪 VLM 定位失敗 | — | 觸發 Rescue 模式，切換備案 |
| Console Log 事件缺失 | 連續 5 輪無事件 | 判定遊戲異常，中斷並報告 |
| Debug Console 可開啟 | 開啟手勢/按鍵有回應 | 啟用 Debug Console 指定盤面模式 |
| Debug Bridge 可用 | `window.__QA_STATE__` 存在 | 優先使用 Debug Bridge 路線 |

### 實施優先級

1. **立即可做**：調查 DEV/UAT 環境 Debug Console 的開啟方式與指令清單，用 Playwright 做 PoC
2. **立即可做**：強化 `game_console_listener.py`，將 Console Log 事件封裝為狀態機 API
3. **一週內完成**：封裝 `debug_console.py` 模組，支援主力遊戲的指定盤面與 Feature 觸發
4. **一週內完成**：建立 Template Matching 模組，先支援 2-3 款主力遊戲
5. **同步推動**：向開發團隊提案 Unity Debug Bridge，先爭取 Repo 實驗權限
6. **中期**：Debug Bridge PoC 驗證後整合進框架，作為最高優先級的狀態來源
7. **持續優化**：在穩定框架上逐步回補 VLM 能力，以數據驅動判斷何時啟用 Vision
