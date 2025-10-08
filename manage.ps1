<#
Usage:
  .\manage.ps1 start      # docker up + 2 uvicorn from .venv + frontend
  .\manage.ps1 stop       # stop all
  .\manage.ps1 restart    # restart
  .\manage.ps1 status     # show status
#>

param(
  [ValidateSet("start","stop","restart","status")]
  [string]$cmd = "status"
)

# -------- Project settings --------
$ProjectName = "supplyhub"
$FrontendDir = "frontend"
$RequireVenv = $true

$UvicornServices = @(
  @{
    Name = "json_filler"
    Args = @("app.mock_services.chatgpt_json_filler:app","--host","127.0.0.1","--port","9002","--log-level","debug")
    Log  = "uvicorn_json_filler.log"
    Pid  = ".pids\json_filler.pid"
  }
)

$FrontendLog = "frontend.log"
$FrontendPid = ".pids\frontend.pid"

# -------- Helpers --------
function Ensure-PidDir {
  if (-not (Test-Path ".pids")) { New-Item -ItemType Directory -Path ".pids" | Out-Null }
}

function Is-Running([int]$processId) {
  try { Get-Process -Id $processId -ErrorAction Stop | Out-Null; return $true } catch { return $false }
}

function Get-VenvPython {
  $venvPy = ".venv\Scripts\python.exe"
  if (Test-Path $venvPy) { return (Resolve-Path $venvPy).Path }
  return $null
}

function Require-Venv-And-Uvicorn {
  $py = Get-VenvPython
  if (-not $py) {
    Write-Host "No .venv detected. Creating .venv ..."
    # Prefer Windows launcher if available
    $created = $false
    try {
      & py -3 -m venv .venv 2>$null
      if ($LASTEXITCODE -eq 0) { $created = $true }
    } catch { }

    if (-not $created) {
      try {
        & python -m venv .venv 2>$null
        if ($LASTEXITCODE -eq 0) { $created = $true }
      } catch { }
    }

    $py = Get-VenvPython
    if (-not $py) {
      throw "Could not create .venv automatically. Install Python 3 and run: python -m venv .venv"
    }

    # Ensure pip and install deps
    $pip = Join-Path (Split-Path $py -Parent) "pip.exe"
    if (-not (Test-Path $pip)) {
      & $py -m ensurepip --upgrade
    }
    Write-Host "Installing dependencies into .venv ..."
    if (Test-Path "requirements.txt") {
      & $py -m pip install -r requirements.txt
    } else {
      & $py -m pip install uvicorn[standard] fastapi
    }
  }

  # Verify uvicorn is importable
  $version = & $py -c "import uvicorn,sys; sys.stdout.write(uvicorn.__version__)"
  if ($LASTEXITCODE -ne 0 -or -not $version) {
    Write-Host "uvicorn missing in .venv; installing ..."
    & $py -m pip install uvicorn[standard] fastapi
    $version = & $py -c "import uvicorn,sys; sys.stdout.write(uvicorn.__version__)"
    if ($LASTEXITCODE -ne 0 -or -not $version) {
      throw "uvicorn not found in .venv after install. Try manually: .\\.venv\\Scripts\\pip install uvicorn[standard] fastapi"
    }
  }
  return $py
}

function NpmPath {
  if (Test-Path "$env:ProgramFiles\nodejs\npm.cmd") { return "$env:ProgramFiles\nodejs\npm.cmd" }
  return "npm"
}

# -------- Docker detection & checks --------
function Get-ComposeCommand {
  # prefer docker compose (v2)
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    $null = & docker compose version 2>$null
    if ($LASTEXITCODE -eq 0) { return @{Exe="docker"; Args=@("compose","-p",$ProjectName)} }
  }
  # fallback to docker-compose (v1)
  if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
    return @{Exe="docker-compose"; Args=@("-p",$ProjectName)}
  }
  throw "Docker Compose is not available. Install/enable Docker Desktop (compose v2) or docker-compose."
}

function Check-Docker {
  $null = & docker info 2>$null
  if ($LASTEXITCODE -ne 0) { throw "Docker Engine is not running. Start Docker Desktop and try again." }
}

function Start-Docker {
  Write-Host "Docker: compose up --build ..."
  if (-not (Test-Path "docker-compose.yml")) { throw "docker-compose.yml not found in $(Get-Location). Run script from project root." }
  $cc = Get-ComposeCommand
  $output = & $cc.Exe @($cc.Args + @("up","--build","-d")) 2>&1
  if ($LASTEXITCODE -ne 0) { $output | Out-File -Encoding UTF8 "docker_start_error.log"; throw "Compose up failed. See docker_start_error.log" }
  Write-Host "Docker: services are up."
}

function Stop-Docker {
  Write-Host "Docker: compose down ..."
  $cc = Get-ComposeCommand
  $output = & $cc.Exe @($cc.Args + @("down")) 2>&1
  if ($LASTEXITCODE -ne 0) { $output | Out-File -Encoding UTF8 "docker_stop_error.log"; throw "Compose down failed. See docker_stop_error.log" }
  Write-Host "Docker: services are down."
}

# -------- Uvicorn --------
function Start-UvicornServices {
  Ensure-PidDir
  $python   = Require-Venv-And-Uvicorn
  $rootPath = (Get-Location).Path

  foreach ($svc in $UvicornServices) {
    Write-Host ("Starting uvicorn [{0}] via .venv ..." -f $svc.Name)

    $args = @("-m","uvicorn","--app-dir",$rootPath) + $svc.Args
    $outLog = Join-Path -Path $rootPath -ChildPath $svc.Log
    $errLog = [System.IO.Path]::ChangeExtension($outLog, ".err.log")

    # Start process detached, redirecting to separate stdout/stderr files
    $proc = Start-Process -FilePath $python `
                          -ArgumentList $args `
                          -WorkingDirectory $rootPath `
                          -WindowStyle Hidden `
                          -RedirectStandardOutput $outLog `
                          -RedirectStandardError $errLog `
                          -PassThru

    Set-Content -Path $svc.Pid -Value $proc.Id
    Write-Host (" -> PID {0}, logs: {1}, {2}" -f $proc.Id, [System.IO.Path]::GetFileName($outLog), [System.IO.Path]::GetFileName($errLog))
  }
}

function Stop-ByPidFile($pidFile, $label) {
  if (Test-Path $pidFile) {
    $procId = (Get-Content $pidFile).Trim()
    if ($procId -match '^\d+$' -and (Is-Running([int]$procId))) {
      Write-Host ("Stopping {0} (PID {1}) ..." -f $label, $procId)
      try { Stop-Process -Id ([int]$procId) -Force -ErrorAction Stop } catch {}
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
  } else {
    Write-Host ("{0} is not running (no PID file)." -f $label)
  }
}

function Get-PortOwnerPid([int]$port) {
  if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) { return [int]$c.OwningProcess }
  }
  $lines = netstat -ano | Select-String (":$port\s")
  foreach ($l in $lines) {
    $parts = $l.Line -split '\s+'
    if ($parts.Length -ge 5) { return [int]$parts[-1] }
  }
  return $null
}

function Kill-Port([int]$port) {
  $owner = Get-PortOwnerPid $port
  if ($owner) {
    try {
      Stop-Process -Id $owner -Force -ErrorAction Stop
      Write-Host ("Killed PID {0} listening on port {1}" -f $owner, $port)
    } catch {
      Write-Host ("Failed to kill PID {0} on port {1}: {2}" -f $owner, $port, $_.Exception.Message)
    }
  }
}

function Get-PortFromArgs($argsArray) {
  for ($i=0; $i -lt $argsArray.Count; $i++) {
    if ($argsArray[$i] -eq "--port" -and $i -lt ($argsArray.Count-1)) {
      return [int]$argsArray[$i+1]
    }
  }
  return $null
}

function Kill-UvicornBySignature($svc) {
  $sig = $svc.Args[0]  # "module:app"
  try {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"
    foreach ($p in $procs) {
      if ($p.CommandLine -and $p.CommandLine -match "uvicorn" -and $p.CommandLine -match [regex]::Escape($sig)) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Host ("Killed PID {0} by signature {1}" -f $p.ProcessId,$sig) } catch {}
      }
    }
  } catch { }
}

function Stop-UvicornServices {
  foreach ($svc in $UvicornServices) {
    # 1) по PID-файлу
    Stop-ByPidFile $svc.Pid ("uvicorn:" + $svc.Name)
    # 2) по сигнатуре командной строки
    Kill-UvicornBySignature $svc
    # 3) по порту
    $port = Get-PortFromArgs $svc.Args
    if ($port) { Kill-Port $port }
  }
}

# -------- Frontend --------
function Start-Frontend {
  # Если каталога фронта или package.json нет — просто пропустим шаг
  if (-not (Test-Path $FrontendDir)) {
    Write-Host ("Skipping frontend: directory '{0}' not found." -f $FrontendDir)
    return
  }
  if (-not (Test-Path (Join-Path $FrontendDir "package.json"))) {
    Write-Host ("Skipping frontend: '{0}\package.json' not found." -f $FrontendDir)
    return
  }

  Ensure-PidDir
  $npm = NpmPath
  Write-Host ("Starting frontend in '{0}': npm run dev ..." -f $FrontendDir)
  $rootPath = (Get-Location).Path

  Push-Location $FrontendDir
  try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $npm
    $psi.Arguments = "run dev"
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $null = $proc.Start()

    $logPath = Join-Path -Path $rootPath -ChildPath $FrontendLog
    $sw = [System.IO.StreamWriter]::new($logPath,$true)
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()
    $proc.add_OutputDataReceived({ param($s,$e) if ($e.Data) { $sw.WriteLine($e.Data) }})
    $proc.add_ErrorDataReceived({ param($s,$e) if ($e.Data) { $sw.WriteLine($e.Data) }})

    Set-Content -Path (Join-Path -Path $rootPath -ChildPath $FrontendPid) -Value $proc.Id
    Write-Host (" -> PID {0}, log: {1}" -f $proc.Id, $FrontendLog)
  } finally {
    Pop-Location
  }
}


function Stop-Frontend {
  Stop-ByPidFile $FrontendPid "frontend"
}

function Show-Status {
  Write-Host "=== STATUS ==="

  foreach ($svc in $UvicornServices) {
    if (Test-Path $svc.Pid) {
      $procId = ((Get-Content $svc.Pid | Select-Object -First 1) -as [string])
      if ([string]::IsNullOrWhiteSpace($procId)) {
        Write-Host ("uvicorn:{0,-12} not started" -f $svc.Name)
      } elseif ($procId -match '^\d+$' -and (Is-Running([int]$procId))) {
        Write-Host ("uvicorn:{0,-12} RUNNING (PID {1})" -f $svc.Name, $procId)
      } else {
        Write-Host ("uvicorn:{0,-12} DEAD (PID {1})" -f $svc.Name, $procId)
      }
    } else {
      Write-Host ("uvicorn:{0,-12} not started" -f $svc.Name)
    }
  }

  if (Test-Path $FrontendPid) {
    $fePid = ((Get-Content $FrontendPid | Select-Object -First 1) -as [string])
    if ([string]::IsNullOrWhiteSpace($fePid)) {
      Write-Host "frontend        not started"
    } elseif ($fePid -match '^\d+$' -and (Is-Running([int]$fePid))) {
      Write-Host ("frontend        RUNNING (PID {0})" -f $fePid)
    } else {
      Write-Host ("frontend        DEAD (PID {0})" -f $fePid)
    }
  } else {
    Write-Host "frontend        not started"
  }

  try {
    $cc = Get-ComposeCommand
    $dc = ($cc.Args -join ' ')
    Write-Host ("(for docker status: {0} {1} ps)" -f $cc.Exe, $dc)
  } catch {
    Write-Host "(docker not detected)"
  }
}


# -------- Main --------
try {
  switch ($cmd) {
    "start"   { Check-Docker; Start-Docker; Start-UvicornServices; Start-Frontend; Show-Status }
    "stop"    { Stop-Frontend; Stop-UvicornServices; Stop-Docker; Show-Status }
    "restart" { & $PSCommandPath stop; Start-Sleep -Seconds 2; & $PSCommandPath start }
    default   { Show-Status }
  }
  exit 0
}
catch {
  Write-Host ""
  Write-Host ("ERROR: {0}" -f $_.Exception.Message)
  if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
    Write-Host $_.InvocationInfo.PositionMessage
  }
  exit 2
}

