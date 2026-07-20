<#
.SYNOPSIS
    全量跑 FC + JDB 單手下注測試，結束後自動用 --lf 重跑第一輪的 fail。

.DESCRIPTION
    第一輪：完整跑 test_game_betting_fc + test_game_betting_jdb。
    第二輪：若第一輪有任何 fail/error，自動 `pytest --lf` 只重跑失敗案例，
            用來吸收 network error / 進 free game 等偶發性失敗。

    兩輪共用同一個 .pytest_cache，因此需在同一台機器、同一 repo 連續執行。
    每輪的 artifact 皆帶各自時間戳歸檔於 test_artifacts/{provider}/{pass|fail}/，
    重跑不會覆蓋第一輪結果。

.PARAMETER Env
    測試環境，預設 uat（對應 pytest --env）。

.PARAMETER Reruns
    最多重跑幾輪 fail，預設 1。設 0 則只跑全量、不重跑。

.PARAMETER ExtraArgs
    透傳給 pytest 的額外參數（例如 -k "Robin Hood"）。

.EXAMPLE
    ./scripts/run_fc_jdb_full_with_rerun.ps1

.EXAMPLE
    ./scripts/run_fc_jdb_full_with_rerun.ps1 -Env uat -Reruns 2
#>
[CmdletBinding()]
param(
    [string]$Env = "uat",
    [int]$Reruns = 1,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $targets = @(
        "tests/test_game_betting.py::test_game_betting_fc",
        "tests/test_game_betting.py::test_game_betting_jdb"
    )

    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host " Round 1 / full run (FC + JDB, env=$Env)" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan

    $env:FORCE_AUTO_PLAY_RUN = "1"
    $fullArgs = @("-m", "pytest") + $targets + @("--env", $Env, "-v") + $ExtraArgs
    & python @fullArgs
    $firstExit = $LASTEXITCODE
    Write-Host "Round 1 exit code: $firstExit"

    if ($firstExit -eq 0) {
        Write-Host "Round 1 all passed; no rerun needed." -ForegroundColor Green
        exit 0
    }

    $lastExit = $firstExit
    for ($i = 1; $i -le $Reruns; $i++) {
        Write-Host "==================================================================" -ForegroundColor Yellow
        Write-Host " Rerun $i / $Reruns (only last-failed, env=$Env)" -ForegroundColor Yellow
        Write-Host "==================================================================" -ForegroundColor Yellow

        $env:FORCE_AUTO_PLAY_RUN = "$($i + 1)"
        $rerunArgs = @("-m", "pytest") + $targets + @("--env", $Env, "-v", "--lf") + $ExtraArgs
        & python @rerunArgs
        $lastExit = $LASTEXITCODE
        Write-Host "Rerun $i exit code: $lastExit"

        if ($lastExit -eq 0) {
            Write-Host "Rerun $i cleared all remaining failures." -ForegroundColor Green
            break
        }
    }

    # 以最後一輪的結果作為整體結束碼（第二輪 pass 即視為通過）。
    exit $lastExit
}
finally {
    Pop-Location
}
