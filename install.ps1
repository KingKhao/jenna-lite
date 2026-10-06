# Jenna Lite installer. Run it by double-clicking "Install Jenna Lite.cmd" (no admin needed).
# Safe to run again any time: it only adds what's missing, and never touches your Brain notes or settings.
#   1. Python 3.12, Ollama (her AI engine) and FFmpeg, through winget, if they aren't installed
#   2. her Python packages, in a private folder (.venv) next to this script
#   3. her voice (Kokoro, ~340 MB) and her brain (a Qwen3 model sized for your graphics card, 2.5-9 GB)
#   4. Desktop, Start menu and sign-in shortcuts, then opens her setup screen
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
# a downloaded zip marks every file 'from the internet'; clear that for her own folder so Python can load them
Get-ChildItem -Path $here -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $here 'data') | Out-Null
Start-Transcript -Path (Join-Path $here 'data\install-log.txt') -Force | Out-Null

function Say($text, $color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Step($n, $text) { Write-Host "`n[$n/7] $text" -ForegroundColor Cyan }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Winget-Install($id, $name) {
    if (-not (Have 'winget')) { throw "winget isn't available. Install '$name' yourself, then run this again." }
    Say "  Installing $name (a window may ask for permission)..."
    winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements --scope user 2>$null
    if ($LASTEXITCODE -ne 0) {   # some packages only offer a machine-wide install
        winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
    }
    Refresh-Path
}

try {
    Say "`n  Jenna Lite - a private AI assistant that runs on this PC`n  by Clinch Valley Digital  |  built with ideas from hellotrillion.ai`n" 'Magenta'

    # ---------------------------------------------------------------- 1. Python
    Step 1 'Python'
    $py = $null
    foreach ($v in '3.12', '3.11') {
        if (Have 'py') { try { $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $p) { $py = $p.Trim(); break } } catch {} }
    }
    if (-not $py) {
        Winget-Install 'Python.Python.3.12' 'Python 3.12'
        $cand = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
        if (Test-Path $cand) { $py = $cand } elseif (Have 'py') { $py = (& py -3.12 -c "import sys; print(sys.executable)").Trim() }
    }
    if (-not $py) { throw 'Python 3.12 could not be installed. Install it from python.org, then run this again.' }
    Say "  Using $py" 'Green'

    # ---------------------------------------------------------------- 2. Ollama + FFmpeg
    Step 2 'Ollama (her AI engine) and FFmpeg (voice notes)'
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama) { $c = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'; if (Test-Path $c) { $ollama = $c } }
    if (-not $ollama) {
        Winget-Install 'Ollama.Ollama' 'Ollama'
        $c = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        $ollama = if (Test-Path $c) { $c } else { (Get-Command ollama -ErrorAction SilentlyContinue).Source }
    }
    if (-not $ollama) { throw 'Ollama could not be installed. Get it from ollama.com, then run this again.' }
    $up = $false
    try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null; $up = $true } catch {}
    if (-not $up) {
        $app = Join-Path (Split-Path $ollama) 'ollama app.exe'
        if (Test-Path $app) { Start-Process $app } else { Start-Process $ollama -ArgumentList 'serve' -WindowStyle Hidden }
        for ($i = 0; $i -lt 30 -and -not $up; $i++) {
            Start-Sleep 2; try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null; $up = $true } catch {}
        }
    }
    if (-not $up) { throw "Ollama is installed but didn't start. Open 'Ollama' from the Start menu, then run this again." }
    Say '  Ollama is running.' 'Green'
    if (-not (Have 'ffmpeg') -and -not (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*" -ErrorAction SilentlyContinue)) {
        try { Winget-Install 'Gyan.FFmpeg' 'FFmpeg' } catch { Say '  FFmpeg skipped (only needed for Telegram voice notes).' 'Yellow' }
    }

    # ---------------------------------------------------------------- 3. Python packages
    Step 3 'Her Python packages (a few minutes the first time)'
    $venv = Join-Path $here '.venv'
    if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) { & $py -m venv $venv }
    $vpy = Join-Path $venv 'Scripts\python.exe'
    $vpyw = Join-Path $venv 'Scripts\pythonw.exe'
    & $vpy -m pip install --upgrade pip --quiet --disable-pip-version-check
    # the lock file pins every package to the versions she was tested with (a new library release once broke voice)
    $reqs = if (Test-Path (Join-Path $here 'requirements.lock')) { 'requirements.lock' } else { 'requirements.txt' }
    & $vpy -m pip install -r (Join-Path $here $reqs) --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'Installing her packages failed (see the messages above).' }
    & $vpy -m playwright install chromium 2>$null | Out-Null
    Say '  Packages ready.' 'Green'

    # ---------------------------------------------------------------- 4. voice
    Step 4 'Her voice (Kokoro)'
    $vdir = Join-Path $here 'voices'
    New-Item -ItemType Directory -Force $vdir | Out-Null
    $base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'
    foreach ($f in 'kokoro-v1.0.onnx', 'voices-v1.0.bin') {
        $dest = Join-Path $vdir $f
        if (-not (Test-Path $dest) -or (Get-Item $dest).Length -lt 1MB) {
            Say "  Downloading $f..."
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest "$base/$f" -OutFile "$dest.part" -UseBasicParsing
            Move-Item "$dest.part" $dest -Force
        }
    }
    Say '  Voice ready.' 'Green'

    # ---------------------------------------------------------------- 5. brain (model sized to the graphics card)
    Step 5 'Her brain (the AI model)'
    $vram = 0
    if (Have 'nvidia-smi') {
        try { $vram = [int]((nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | Select-Object -First 1).Trim()) / 1024 } catch {}
    }
    $cfgPath = Join-Path $here 'config.json'
    $cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
    if (-not $cfg.model) {
        if ($vram -ge 11.5) { $model = 'qwen3:14b'; $ctx = 12288 } elseif ($vram -ge 7.5) { $model = 'qwen3:8b'; $ctx = 8192 } else { $model = 'qwen3:4b'; $ctx = 8192 }
        $cfg | Add-Member -NotePropertyName model -NotePropertyValue $model -Force
        $cfg | Add-Member -NotePropertyName num_ctx -NotePropertyValue $ctx -Force
        $cfg | ConvertTo-Json -Depth 5 | Set-Content $cfgPath -Encoding utf8
    }
    $model = $cfg.model
    Say ("  Graphics memory: {0:N1} GB -> {1}" -f $vram, $model)
    Say "  Downloading $model (one time; this is the big one)..."
    & $ollama pull $model
    if ($LASTEXITCODE -ne 0) { throw "Downloading $model failed - check the internet connection and run this again." }
    & $ollama pull nomic-embed-text   # small: lets her recall memories by meaning
    Say '  Brain ready.' 'Green'

    # ---------------------------------------------------------------- 6. shortcuts
    Step 6 'Shortcuts'
    $ws = New-Object -ComObject WScript.Shell
    $icon = Join-Path $here 'pc\jenna.ico'
    function Make-Link($path, $script, $desc) {
        $s = $ws.CreateShortcut($path)
        $s.TargetPath = $vpyw
        $s.Arguments = "`"$(Join-Path $here $script)`""
        $s.WorkingDirectory = $here
        $s.Description = $desc
        if (Test-Path $icon) { $s.IconLocation = $icon }
        $s.Save()
    }
    Make-Link (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jenna Lite.lnk') 'open_app.py' 'Open Jenna Lite'
    Make-Link (Join-Path ([Environment]::GetFolderPath('Programs')) 'Jenna Lite.lnk') 'open_app.py' 'Open Jenna Lite'
    Make-Link (Join-Path ([Environment]::GetFolderPath('Startup')) 'Jenna Lite (background).lnk') 'run_jenna.py' 'Starts Jenna Lite when you sign in'
    Say '  Desktop and Start menu icons added; she starts in the background when you sign in.' 'Green'

    # ---------------------------------------------------------------- 7. start
    Step 7 'Starting her'
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like "*$here*run_jenna.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Process -FilePath $vpyw -ArgumentList "`"$(Join-Path $here 'run_jenna.py')`"" -WorkingDirectory $here
    Start-Sleep 3
    Start-Process -FilePath $vpyw -ArgumentList "`"$(Join-Path $here 'open_app.py')`"" -WorkingDirectory $here
    Say "`n  All set. Her setup screen is opening - answer a few questions and she's yours." 'Green'
}
catch {
    Say "`n  Something went wrong: $($_.Exception.Message)" 'Red'
    Say "  A log of this window was saved to $here\data\install-log.txt"
}
finally {
    Stop-Transcript | Out-Null
    Read-Host "`n  Press Enter to close"
}
