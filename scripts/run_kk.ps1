# Полный прогон по данным кейса: проверка (правила + LLM), HTML-отчёт и таблица для носителя.
#
#   .\scripts\run_kk.ps1           # LLM смотрит находки правил и подозрительные строки (~5 запросов)
#   .\scripts\run_kk.ps1 -All      # LLM смотрит все строки (~130 запросов, около 20 минут на бесплатном тарифе)
#   .\scripts\run_kk.ps1 -NoLlm    # только правила, без ключа и сети
#   .\scripts\run_kk.ps1 -Test     # пробный прогон LLM на 20 строках
param(
    [switch]$All,
    [switch]$NoLlm,
    [switch]$Test
)

$root = Split-Path -Parent $PSScriptRoot
$locqa = Join-Path $root ".venv\Scripts\locqa.exe"
if (-not (Test-Path $locqa)) {
    Write-Host "Не найден $locqa. Установите: python -m venv .venv; .venv\Scripts\pip install -e "".[dev,llm]""" -ForegroundColor Red
    exit 2
}
Set-Location $root

$checkArgs = @(
    "check",
    "--source", "data/intl_ru.arb",
    "--target", "data/intl_kk.arb",
    "--glossary", "glossary/glossary.csv",
    "--context", "data/intl_en.arb",
    "--context", "data/intl_uz.arb",
    "--out", "out/report.json",
    "--html", "out/report.html"
)
if (-not $NoLlm) {
    $checkArgs += "--llm"
    if ($All) { $checkArgs += @("--llm-scope", "all") }
    if ($Test) { $checkArgs += @("--max-llm-strings", "20") }
}

Write-Host "== 1/2 Проверка" -ForegroundColor Cyan
& $locqa @checkArgs
$code = $LASTEXITCODE
if ($code -eq 2) { Write-Host "Ошибка входных данных, см. выше." -ForegroundColor Red; exit 2 }
if ($code -eq 3) {
    Write-Host "LLM не отработал (см. сообщение выше). Результаты правил сохранены, продолжаю." -ForegroundColor Yellow
}

Write-Host "== 2/2 Таблица для носителя" -ForegroundColor Cyan
& $locqa review-sheet --report out/report.json --out out/review.csv --min-severity medium

Write-Host ""
Write-Host "Готово:" -ForegroundColor Green
Write-Host "  out/report.html  - отчёт, откройте в браузере"
Write-Host "  out/review.csv   - таблица для носителя (Excel): decision = accept / edit / reject"
if (Test-Path "out/cost.json") { Write-Host "  out/cost.json    - токены и стоимость LLM" }
Write-Host ""
Write-Host "После проверки носителем:"
Write-Host "  .venv\Scripts\locqa apply --source data/intl_ru.arb --target data/intl_kk.arb --review out/review.csv --out out/intl_kk_fixed.arb --report out/report.json"
Write-Host "  .venv\Scripts\locqa validate --source data/intl_ru.arb --target out/intl_kk_fixed.arb --original data/intl_kk.arb"
