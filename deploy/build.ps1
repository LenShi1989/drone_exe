# 打包 DroneServer.exe 與 DroneClient.exe 到 dist\DroneSystem\
#   powershell -ExecutionPolicy Bypass -File deploy\build.ps1
#   -Python <路徑>  指定 Python (預設 python)
#   -Clean          先清掉 build\ 與 dist\
param(
    [string]$Python = "python",
    [switch]$Clean
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Clean) {
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
}

Write-Host "== 安裝 / 確認相依套件" -ForegroundColor Cyan
& $Python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install 失敗" }

foreach ($spec in "DroneServer", "DroneClient") {
    Write-Host "== 建置 $spec.exe" -ForegroundColor Cyan
    & $Python -m PyInstaller "deploy\$spec.spec" --noconfirm --distpath dist --workpath "build\$spec"
    if ($LASTEXITCODE -ne 0) { throw "$spec 建置失敗" }
}

$out = Join-Path $root "dist\DroneSystem"
New-Item -ItemType Directory -Force $out | Out-Null
Move-Item -Force dist\DroneServer.exe, dist\DroneClient.exe $out
Copy-Item -Force deploy\server.ini.example (Join-Path $out "server.ini")
Copy-Item -Force deploy\client.ini.example (Join-Path $out "client.ini")
Copy-Item -Force db\init_postgreSQL.sql $out
Copy-Item -Force deploy\README.md (Join-Path $out "README.md")

Write-Host ""
Write-Host "完成:$out" -ForegroundColor Green
Get-ChildItem $out | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } } | Format-Table
