# Removes Jenna Lite's shortcuts, stops her, turns off phone access and forgets the Telegram token.
# Your Brain notes folder is NOT deleted (it's yours). Ollama and its models stay too - remove them from Windows
# "Installed apps" if you like. Delete this folder afterwards to remove the rest.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "`n  Removing Jenna Lite...`n" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like "*$here*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
foreach ($p in @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jenna Lite.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'Jenna Lite.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Startup')) 'Jenna Lite (background).lnk'))) {
    if (Test-Path $p) { Remove-Item $p -Force; Write-Host "  removed $p" }
}
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
$cfg = Join-Path $here 'config.json'
if ((Test-Path $ts) -and (Test-Path $cfg) -and ((Get-Content $cfg -Raw) -match '"pc_remote_hosts":\s*\[\s*"')) {
    & $ts serve --https=443 off 2>$null | Out-Null
    Write-Host '  phone access (tailscale serve) turned off'
}
$vpy = Join-Path $here '.venv\Scripts\python.exe'
if (Test-Path $vpy) {
    & $vpy -c "import keyring; keyring.delete_password('jenna-lite', 'telegram_token')" 2>$null
    Write-Host '  Telegram token removed from Credential Manager (if there was one)'
}
Write-Host "`n  Done. Your Brain folder was kept. Delete $here to remove the program files." -ForegroundColor Green
Read-Host "`n  Press Enter to close"
