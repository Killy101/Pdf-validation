<#
.SYNOPSIS
  Starts the PDF Validation desktop app, waits until its validation engine is ready and logs every step.
.DESCRIPTION
  Used by run.bat. By default it starts the packaged app (release\win-unpacked from "npm run build", or the copy
  installed by the setup program). The app owns the single validation engine process; this script checks the files,
  stops leftovers from a crashed run, waits until the engine reports ready and reports problems with the logs kept.
    -Build      Build the packaged app first (needs Node.js and Python), then start it.
    -Dev        Development mode: run from source with the Next.js dev server (npm run dev).
    -AppPath    Start a specific "PDF Validation.exe".
    -CheckOnly  Report the state of the setup without installing or starting anything.
#>
[CmdletBinding()]
param([switch]$CheckOnly, [switch]$Dev, [switch]$Build, [string]$AppPath)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$LogRoot = Join-Path $Root 'logs'
$SessionId = Get-Date -Format 'yyyyMMdd-HHmmss'
$DevPort = 3000
$ReadyTimeoutSeconds = 180
$script:Reported = $false
$script:Pending = New-Object System.Collections.ArrayList
$script:ToolCommand = @{}

# ---------------------------------------------------------------- logging

function Get-LogFolder {
    $folder = Join-Path $LogRoot (Get-Date -Format 'yyyy-MM-dd')
    if (-not (Test-Path -LiteralPath $folder)) { [void](New-Item -ItemType Directory -Path $folder -Force) }
    return $folder
}

function Add-SharedText([string]$Path, [string]$Text) {
    $stream = New-Object System.IO.FileStream($Path, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
    try {
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Text)
        $stream.Write($bytes, 0, $bytes.Length)
    } finally { $stream.Dispose() }
}

function Read-SharedText([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    try {
        $stream = New-Object System.IO.FileStream($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try { return (New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)).ReadToEnd() } finally { $stream.Dispose() }
    } catch { return '' }
}

function Format-LogValue($Value) {
    $text = [string]$Value
    if ($text -match '^[A-Za-z0-9_./:@%+-]+$') { return $text }
    $escaped = $text.Replace('\', '\\').Replace('"', '\"').Replace("`r", '\r').Replace("`n", '\n').Replace("`t", '\t')
    return '"' + $escaped + '"'
}

# Same line format as the backend and the desktop shell; a logging problem never stops the launcher.
function Write-Log([string]$Level, [string]$Event, [System.Collections.IDictionary]$Fields = $null) {
    try {
        $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss.fff')
        $line = '{0} | {1} | app.launcher | session={2} req=- | event={3}' -f $stamp, $Level.PadRight(8), $SessionId, $Event
        if ($Fields) { foreach ($key in $Fields.Keys) { $line += ' ' + $key + '=' + (Format-LogValue $Fields[$key]) } }
        Add-SharedText (Join-Path (Get-LogFolder) 'application.log') ($line + "`r`n")
    } catch { }
}

function Write-ToolLog([string]$Text) {
    try { Add-SharedText (Join-Path (Get-LogFolder) 'shell.log') ($Text + "`r`n") } catch { }
}

# ---------------------------------------------------------------- console

$script:StepCount = 6
$script:StepOffset = 0
function Show-Step([int]$Number, [string]$Text) {
    Write-Host ''; Write-Host ('[{0}/{1}] {2}' -f ([math]::Min($Number + $script:StepOffset, $script:StepCount)), $script:StepCount, $Text) -ForegroundColor Cyan
}
function Show-Ok([string]$Text) { Write-Host ('      OK    ' + $Text) -ForegroundColor Green }
function Show-Info([string]$Text) { Write-Host ('      ' + $Text) }
function Show-Warn([string]$Text) { Write-Host ('      NOTE  ' + $Text) -ForegroundColor Yellow }

function Show-Failure([string]$Title, [string]$Detail, [string]$Fix) {
    Write-Host ''
    Write-Host ('  [FAILED] ' + $Title) -ForegroundColor Red
    if ($Detail) { Write-Host ''; foreach ($row in ($Detail -split "`r?`n")) { Write-Host ('  ' + $row) } }
    if ($Fix) { Write-Host ''; Write-Host '  What to do:' -ForegroundColor Yellow; foreach ($row in ($Fix -split "`r?`n")) { Write-Host ('    ' + $row) } }
    Write-Host ''
    Write-Host ('  Logs for this run: ' + (Get-LogFolder) + '   (session ' + $SessionId + ')')
}

# Reports the problem once, logs it and ends the launch.
function Stop-Launch([string]$Title, [string]$Detail = '', [string]$Fix = '') {
    Write-Log 'ERROR' 'launcher.failed' ([ordered]@{ reason = $Title; detail = $Detail })
    Show-Failure $Title $Detail $Fix
    $script:Reported = $true
    throw 'LAUNCH_FAILED'
}

function Get-Tail([string]$Text, [int]$Lines) {
    $all = @($Text -split "`r?`n" | Where-Object { $_ -ne '' })
    if ($all.Count -le $Lines) { return ($all -join "`r`n") }
    return (($all | Select-Object -Last $Lines) -join "`r`n")
}

# ---------------------------------------------------------------- helpers

function Invoke-Tool([string]$File, [string]$Arguments, [string]$WorkDir = $Root, [switch]$NoLog) {
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $info = @{ FilePath = $File; WorkingDirectory = $WorkDir; NoNewWindow = $true; Wait = $true; PassThru = $true
                   RedirectStandardOutput = $outFile; RedirectStandardError = $errFile }
        if ($Arguments) { $info.ArgumentList = $Arguments }
        $process = Start-Process @info
        $code = $process.ExitCode
        $text = ((Read-SharedText $outFile) + (Read-SharedText $errFile)).Trim()
    } catch {
        $code = -1
        $text = 'Could not run the program: ' + $_.Exception.Message
    } finally {
        Remove-Item -LiteralPath $outFile, $errFile -ErrorAction SilentlyContinue
    }
    if (-not $NoLog) {
        Write-ToolLog ('=== {0} session={1} cwd={2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $SessionId, $WorkDir)
        Write-ToolLog ('> {0} {1}' -f $File, $Arguments)
        if ($text) { Write-ToolLog $text }
        Write-ToolLog ('--- exit code {0}' -f $code)
    }
    return [pscustomobject]@{ Code = $code; Text = $text }
}

function Find-Command([string]$Name) {
    $found = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.Source }
    return $null
}

function Find-Python {
    $options = @()
    $launcher = Find-Command 'py.exe'
    if ($launcher) { $options += , @($launcher, '-3') }
    foreach ($name in 'python.exe', 'python3.exe') {
        $path = Find-Command $name
        if ($path -and $path -notmatch 'WindowsApps') { $options += , @($path, '') }
    }
    foreach ($option in $options) {
        $probe = (($option[1] + ' -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])"').Trim())
        $result = Invoke-Tool $option[0] $probe -NoLog
        $version = 0
        if ($result.Code -eq 0 -and [int]::TryParse($result.Text, [ref]$version) -and $version -ge 310) {
            return [pscustomobject]@{ Exe = $option[0]; Prefix = $option[1]; Version = ('{0}.{1}' -f [math]::Floor($version / 100), ($version % 100)) }
        }
    }
    return $null
}

function Stop-Tree([int]$ProcessId) {
    try { & cmd.exe /d /c ('taskkill /PID {0} /T /F >nul 2>&1' -f $ProcessId) } catch { }
}

function Get-ProcessInfo([int]$ProcessId) {
    try { return Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ProcessId) -ErrorAction Stop } catch { return $null }
}

function Get-Sidecars {
    try {
        $dev = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -match 'run_server\.py\s+--port\s+\d+\s+--exit-on-stdin-close' })
        # Packaged engines of this app copy only; another installation's engine is left alone.
        $packaged = @()
        if ($script:AppDir) {
            $packaged = @(Get-CimInstance Win32_Process -Filter "Name='pdf-validation-backend.exe'" -ErrorAction Stop |
                Where-Object { $_.ExecutablePath -and $_.ExecutablePath.ToLower().StartsWith($script:AppDir.ToLower()) -and
                               $_.CommandLine -match '--exit-on-stdin-close' })
        }
        return @($dev + $packaged)
    } catch { return @() }
}

function Get-PortOwner([int]$Port) {
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
        if ($connection) { return [int]$connection.OwningProcess }
    } catch { }
    return 0
}

function Test-PortFree([int]$Port) {
    if ((Get-PortOwner $Port) -ne 0) { return $false }
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start(); $listener.Stop()
        return $true
    } catch { return $false }
}

function Stop-LeftoverProcesses {
    foreach ($sidecar in (Get-Sidecars)) {
        Write-Log 'WARNING' 'launcher.stopping_stale_backend' ([ordered]@{ pid = $sidecar.ProcessId })
        Stop-Tree ([int]$sidecar.ProcessId)
    }
    $owner = if ($Dev) { Get-PortOwner $DevPort } else { 0 }
    if ($owner -ne 0) {
        $info = Get-ProcessInfo $owner
        if ($info -and $info.CommandLine -and $info.CommandLine.ToLower().Contains($Root.ToLower())) {
            Write-Log 'INFO' 'launcher.stopping_dev_server' ([ordered]@{ pid = $owner })
            Stop-Tree $owner
        }
    }
}

# Output of the app command for this run only (the shell log also holds earlier tool output).
function Get-AppOutput([int]$Lines) {
    $text = Read-SharedText (Join-Path (Get-LogFolder) 'shell.log')
    $marker = 'session=' + $SessionId + ' starting:'
    $at = $text.LastIndexOf($marker)
    if ($at -ge 0) { $text = $text.Substring($at) }
    return (Get-Tail $text $Lines)
}

function Get-SessionFailure {
    $text = Read-SharedText (Join-Path (Get-LogFolder) 'application.log')
    $marker = 'session=' + $SessionId + ' '
    $hits = @($text -split "`r?`n" | Where-Object { $_.Contains($marker) -and $_ -match 'event=(backend\.(spawn_failed|crashed|exited_unexpectedly|exited|watch_failed)|shell\.panic)' })
    if ($hits.Count -gt 0) { return $hits[0] }
    return $null
}

function Test-SessionEvent([string]$Pattern) {
    $text = Read-SharedText (Join-Path (Get-LogFolder) 'application.log')
    return ($text -match ('session=' + [regex]::Escape($SessionId) + ' req=\S+ \| ' + $Pattern))
}

function Get-SessionErrors {
    $text = Read-SharedText (Join-Path (Get-LogFolder) 'application.log')
    $marker = 'session=' + $SessionId + ' '
    return (@($text -split "`r?`n" | Where-Object { $_.Contains($marker) -and $_ -match '\| (ERROR|CRITICAL) ' } | Select-Object -Last 8) -join "`r`n")
}

# ---------------------------------------------------------------- steps

function Test-ProjectFiles {
    Show-Step 1 'Checking project files'
    $required = @('package.json', 'backend\run_server.py', 'backend\requirements.txt', 'backend\app\desktop_main.py',
                  'frontend\package.json', 'electron\tsconfig.json', 'electron\src\main.ts', 'scripts\dev.mjs')
    $missing = @($required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Root $_)) })
    if ($missing.Count -gt 0) {
        Stop-Launch 'Some project files are missing.' ('Missing: ' + ($missing -join ', ')) 'Restore the files (for example re-download or git pull the project) and run run.bat again.'
    }
    Show-Ok ('All {0} required files are present.' -f $required.Count)
    Write-Log 'INFO' 'launcher.files_checked' ([ordered]@{ root = $Root })
}

function Test-Tools {
    Show-Step 2 'Checking required tools'
    $node = Find-Command 'node.exe'
    if (-not $node) {
        Stop-Launch 'Node.js was not found.' '' "Install Node.js 18 or newer (LTS) from https://nodejs.org, then run run.bat again."
    }
    $version = Invoke-Tool $node '--version' -NoLog
    $major = 0
    if ($version.Text -notmatch '^v(\d+)\.' -or -not [int]::TryParse($Matches[1], [ref]$major) -or $major -lt 18) {
        Stop-Launch ('Node.js 18 or newer is required (found: ' + $version.Text + ').') '' 'Install the current LTS version from https://nodejs.org, then run run.bat again.'
    }
    Show-Ok ('Node.js ' + $version.Text)

    $npm = Find-Command 'npm.cmd'
    if (-not $npm) { Stop-Launch 'npm was not found.' '' 'Reinstall Node.js from https://nodejs.org (npm is included), then run run.bat again.' }
    $script:ToolCommand.npm = $npm
    Show-Ok 'npm'

    Write-Log 'INFO' 'launcher.tools_checked' ([ordered]@{ node = $version.Text })
}

function Initialize-Python {
    Show-Step 3 'Preparing the Python backend'
    $venv = Join-Path $Root '.venv'
    $python = Join-Path $venv 'Scripts\python.exe'
    $backend = Join-Path $Root 'backend'

    if ((Test-Path -LiteralPath $python) -and ((Invoke-Tool $python '-c "pass"' -NoLog).Code -ne 0)) {
        Show-Warn 'The Python environment (.venv) is damaged.'
        if ($CheckOnly) { [void]$script:Pending.Add('Recreate the damaged .venv'); return }
        Write-Log 'WARNING' 'launcher.venv_recreated' ([ordered]@{ reason = 'interpreter does not start' })
        Remove-Item -LiteralPath $venv -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath $python)) {
        $found = Find-Python
        if (-not $found) {
            if ($CheckOnly) { Show-Warn 'Python 3.10 or newer was not found.'; [void]$script:Pending.Add('Install Python 3.10+'); return }
            Stop-Launch 'Python 3.10 or newer was not found.' '' 'Install Python from https://www.python.org/downloads (tick "Add python.exe to PATH"), then run run.bat again.'
        }
        if ($CheckOnly) { Show-Warn 'The Python environment (.venv) does not exist yet and will be created on first start.'; [void]$script:Pending.Add('Create .venv and install backend packages'); return }
        Show-Info ('Creating the Python environment with Python ' + $found.Version + ' (first start only)...')
        $created = Invoke-Tool $found.Exe (($found.Prefix + ' -m venv "' + $venv + '"').Trim())
        if ($created.Code -ne 0 -or -not (Test-Path -LiteralPath $python)) {
            Stop-Launch 'The Python environment could not be created.' (Get-Tail $created.Text 8) 'Check that you can write to the project folder, then run run.bat again.'
        }
        Write-Log 'INFO' 'launcher.venv_created' ([ordered]@{ python = $found.Version })
    }

    $importCheck = '-c "import app.desktop_main"'
    $loaded = Invoke-Tool $python $importCheck $backend
    if ($loaded.Code -ne 0) {
        if ($CheckOnly) { Show-Warn 'Backend packages are missing or incomplete.'; [void]$script:Pending.Add('Install backend packages'); return }
        Show-Info 'Installing backend packages (first start only, this can take a few minutes)...'
        Write-Log 'INFO' 'launcher.installing_backend_packages'
        $installed = Invoke-Tool $python ('-m pip install --disable-pip-version-check -r "' + (Join-Path $backend 'requirements.txt') + '"')
        if ($installed.Code -ne 0) {
            Stop-Launch 'The backend packages could not be installed.' (Get-Tail $installed.Text 10) 'Check your internet connection (and any proxy settings), then run run.bat again.'
        }
        $loaded = Invoke-Tool $python $importCheck $backend
        if ($loaded.Code -ne 0) {
            Stop-Launch 'The backend does not start after installing its packages.' (Get-Tail $loaded.Text 12) 'Delete the .venv folder and run run.bat again. If it still fails, send the logs folder to the maintainer.'
        }
    }
    $pythonVersion = (Invoke-Tool $python '--version' -NoLog).Text
    Show-Ok ($pythonVersion + ' with backend packages loaded.')
    Write-Log 'INFO' 'launcher.backend_ready_to_start' ([ordered]@{ python = $pythonVersion })
}

function Initialize-Frontend {
    Show-Step 4 'Preparing the desktop shell and interface'
    $npm = $script:ToolCommand.npm
    $items = @(
        @{ Name = 'desktop shell packages'; Dir = $Root; Marker = 'node_modules\electron\dist\electron.exe' },
        @{ Name = 'interface packages'; Dir = (Join-Path $Root 'frontend'); Marker = 'node_modules\.bin\next.cmd' })
    foreach ($item in $items) {
        if (Test-Path -LiteralPath (Join-Path $item.Dir $item.Marker)) { Show-Ok ($item.Name + ' are installed.'); continue }
        if ($CheckOnly) { Show-Warn ($item.Name + ' are not installed yet.'); [void]$script:Pending.Add('npm install for ' + $item.Name); continue }
        Show-Info ('Installing ' + $item.Name + ' (first start only, this can take a few minutes)...')
        Write-Log 'INFO' 'launcher.npm_install' ([ordered]@{ target = $item.Name })
        $installed = Invoke-Tool $npm 'install --no-audit --no-fund' $item.Dir
        $electronInstall = Join-Path $item.Dir 'node_modules\electron\install.js'
        if (-not (Test-Path -LiteralPath (Join-Path $item.Dir $item.Marker)) -and (Test-Path -LiteralPath $electronInstall)) {
            $installed = Invoke-Tool (Find-Command 'node.exe') ('"' + $electronInstall + '"') $item.Dir
        }
        if ($installed.Code -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $item.Dir $item.Marker))) {
            Stop-Launch ('The ' + $item.Name + ' could not be installed.') (Get-Tail $installed.Text 10) 'Check your internet connection and any proxy settings, then run run.bat again. The Electron runtime is downloaded from github.com; if that is blocked, ask IT to allow it or set the ELECTRON_MIRROR environment variable.'
        }
        Show-Ok ($item.Name + ' installed.')
    }
}

function Test-Instances {
    Show-Step 5 'Checking for a running copy'
    $running = @(Get-Process -Name 'electron' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.ToLower().StartsWith($Root.ToLower()) })
    if ($running.Count -gt 0) {
        Stop-Launch 'PDF Validation is already running.' ('Process id: ' + $running[0].Id) 'Switch to the open PDF Validation window, or close it and run run.bat again.'
    }
    $stale = @(Get-Sidecars)
    if ($stale.Count -gt 0) {
        if ($CheckOnly) { Show-Warn ('{0} leftover backend process(es) found; they would be stopped on start.' -f $stale.Count) } else {
            Show-Info ('Stopping {0} leftover backend process(es) from an earlier run...' -f $stale.Count)
        }
    }
    if (-not $CheckOnly) { Stop-LeftoverProcesses }
    if (-not (Test-PortFree $DevPort)) {
        $owner = Get-PortOwner $DevPort
        $info = if ($owner -ne 0) { Get-ProcessInfo $owner } else { $null }
        $name = if ($info) { '{0} (process id {1})' -f $info.Name, $owner } else { 'another program' }
        if ($CheckOnly) { Show-Warn ('Port {0} is in use by {1}.' -f $DevPort, $name); [void]$script:Pending.Add('Free port ' + $DevPort); return }
        Stop-Launch ('Port {0} is already in use by {1}.' -f $DevPort, $name) 'The desktop app needs this port for its interface during start-up.' ('Close that program (often another development server) and run run.bat again.')
    }
    Show-Ok ('No other copy is running; port {0} is free.' -f $DevPort)
}

# $Command is a cmd.exe command line; its console output is appended to shell.log for this session.
function Start-Application([string]$Command, [string]$WorkDir) {
    Show-Step 99 'Starting PDF Validation'
    $shellLog = Join-Path (Get-LogFolder) 'shell.log'
    $env:PDF_VALIDATION_SESSION_ID = $SessionId
    $env:PDF_VALIDATION_LOG_DIR = $LogRoot
    Write-ToolLog ('=== {0} session={1} starting: {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $SessionId, $Command)
    Write-Log 'INFO' 'app.starting' ([ordered]@{ command = $Command; root = $WorkDir; mode = $(if ($Dev) { 'dev' } else { 'packaged' }) })
    $arguments = '/d /s /c "' + $Command + ' >> "' + $shellLog + '" 2>&1"'
    $process = Start-Process -FilePath 'cmd.exe' -ArgumentList $arguments -WorkingDirectory $WorkDir -WindowStyle Hidden -PassThru
    $script:AppProcess = $process
    Show-Info 'Opening the app (usually a few seconds).'

    $started = Get-Date
    $lastNote = $started
    $ready = $false
    while (-not $ready) {
        if ($process.WaitForExit(1000)) { break }
        $failure = Get-SessionFailure
        if ($failure) {
            Stop-Tree $process.Id
            Stop-Launch 'The backend could not be started.' ((Get-Tail $failure 1) + "`r`n`r`n" + (Get-AppOutput 10)) 'See the application.log and backend.log files in the logs folder for the full details.'
        }
        if (Test-SessionEvent 'event=backend\.ready') { $ready = $true; break }
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        if ($elapsed -ge $ReadyTimeoutSeconds) {
            Stop-Tree $process.Id
            Stop-Launch 'The app did not become ready in time.' (Get-AppOutput 15) 'Open shell.log in the logs folder to see where the start-up stopped.'
        }
        if (((Get-Date) - $lastNote).TotalSeconds -ge 30) {
            Show-Info ('Still starting... ({0} s)' -f $elapsed)
            $lastNote = Get-Date
        }
    }

    if (-not $ready) {
        $code = $process.ExitCode
        $detail = (Get-AppOutput 25)
        $errors = Get-SessionErrors
        if ($errors) { $detail = $errors + "`r`n`r`n" + $detail }
        if (-not $Dev -and $code -eq 0 -and -not $errors) {
            Stop-Launch 'The app closed during start-up without an error.' $detail 'If PDF Validation is already open (for example started from the Start menu), use that window. Otherwise see application.log in the logs folder.'
        }
        Stop-Launch ('The app stopped during start-up (exit code {0}).' -f $code) $detail 'Open shell.log in the logs folder for the complete output. The last lines above usually name the problem.'
    }

    $took = [int]((Get-Date) - $started).TotalSeconds
    Write-Log 'INFO' 'launcher.startup_complete' ([ordered]@{ seconds = $took })
    Write-Host ''
    Write-Host '  [OK] PDF Validation started successfully.' -ForegroundColor Green
    Show-Info ('The validation engine is running (ready after {0} s).' -f $took)
    Show-Info 'Close the app window when you are done. This window will report the shutdown.'

    $warned = $false
    while (-not $process.WaitForExit(2000)) {
        if (-not $warned -and (Test-SessionEvent 'event=backend\.exited_unexpectedly')) {
            $warned = $true
            Show-Warn 'The validation engine stopped unexpectedly. Close the app and run run.bat again. Details are in application.log.'
        }
    }
    return $process.ExitCode
}

# ---------------------------------------------------------------- packaged app

function Get-AppCandidates {
    $list = @()
    if ($AppPath) { return @($AppPath) }
    if ($env:PDF_VALIDATION_APP) { $list += $env:PDF_VALIDATION_APP }
    $list += (Join-Path $Root 'release\win-unpacked\PDF Validation.exe')
    if ($env:LOCALAPPDATA) { $list += (Join-Path $env:LOCALAPPDATA 'Programs\PDF Validation\PDF Validation.exe') }
    if ($env:ProgramFiles) { $list += (Join-Path $env:ProgramFiles 'PDF Validation\PDF Validation.exe') }
    return $list
}

function Build-PackagedApp {
    Show-Info 'Building the desktop app and validation engine (this takes several minutes)...'
    Write-Log 'INFO' 'launcher.build_started'
    $built = Invoke-Tool $script:ToolCommand.npm 'run build' $Root
    if ($built.Code -ne 0) {
        Stop-Launch 'The desktop app could not be built.' (Get-Tail $built.Text 15) 'Open shell.log in the logs folder for the full build output.'
    }
    Write-Log 'INFO' 'launcher.build_finished'
    Show-Ok 'Build finished.'
}

function Find-PackagedApp {
    Show-Step 1 'Finding the desktop app'
    $candidates = @(Get-AppCandidates)
    $found = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $found) {
        Write-Log 'WARNING' 'launcher.app_not_found' ([ordered]@{ checked = ($candidates -join '; ') })
        if ($CheckOnly) { Show-Warn 'The desktop app has not been built or installed yet.'; [void]$script:Pending.Add('Build the app: run.bat -Build'); return $null }
        Stop-Launch 'The PDF Validation desktop app was not found.' ("Checked:`r`n  " + ($candidates -join "`r`n  ")) ("Build it once with:  run.bat -Build   (needs Node.js and Python)`r`nor install it with ""PDF Validation Setup.exe"".`r`nTo run from source for development:  run.bat -Dev")
    }
    $found = (Resolve-Path -LiteralPath $found).Path
    $script:AppDir = Split-Path -Parent $found
    Show-Ok $found
    $version = (Get-Item -LiteralPath $found).VersionInfo.ProductVersion
    Write-Log 'INFO' 'launcher.app_found' ([ordered]@{ path = $found; version = $version })
    return $found
}

function Test-PackagedFiles([string]$Exe) {
    Show-Step 2 'Checking the app files'
    $resources = Join-Path $script:AppDir 'resources'
    $engine = Join-Path $resources 'backend\pdf-validation-backend.exe'
    $required = @($Exe, (Join-Path $resources 'app.asar'), (Join-Path $resources 'frontend\index.html'), $engine, (Join-Path $resources 'backend\_internal'))
    $missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_) })
    if ($missing.Count -gt 0) {
        Stop-Launch 'The desktop app is incomplete.' ('Missing: ' + ($missing -join ', ')) 'Rebuild it with run.bat -Build, or reinstall PDF Validation.'
    }
    Show-Ok 'App, interface and validation engine are present.'
    foreach ($file in $Exe, $engine) {
        $signature = Get-AuthenticodeSignature -LiteralPath $file
        $signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { '-' }
        Write-Log 'INFO' 'launcher.signature' ([ordered]@{ file = (Split-Path -Leaf $file); status = [string]$signature.Status; signer = $signer })
        if ($signature.Status -eq 'Valid') { Show-Ok ((Split-Path -Leaf $file) + ' is signed by ' + $signer) }
        elseif ($signature.Status -eq 'NotSigned') { Show-Info ((Split-Path -Leaf $file) + ' is not code-signed (a development build).') }
        else { Show-Warn ((Split-Path -Leaf $file) + ' has a signature problem: ' + $signature.Status + '. ' + $signature.StatusMessage) }
    }
}

function Test-PackagedInstance([string]$Exe) {
    Show-Step 3 'Checking for a running copy'
    $running = @(Get-Process -Name 'PDF Validation' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path -ieq $Exe })
    if ($running.Count -gt 0) {
        Stop-Launch 'PDF Validation is already running.' ('Process id: ' + $running[0].Id) 'Switch to the open PDF Validation window, or close it and run run.bat again.'
    }
    $stale = @(Get-Sidecars)
    if ($stale.Count -gt 0) {
        if ($CheckOnly) { Show-Warn ('{0} leftover validation engine process(es) found; they would be stopped on start.' -f $stale.Count) } else {
            Show-Info ('Stopping {0} leftover validation engine process(es) from an earlier run...' -f $stale.Count)
            Stop-LeftoverProcesses
        }
    }
    Show-Ok 'No other copy is running.'
}

# ---------------------------------------------------------------- main

$exitCode = 0
$mutex = $null
$ownsInstance = $false
$script:AppProcess = $null
$script:AppDir = $null
$mode = if ($Dev) { 'development (from source, npm run dev)' } elseif ($Build) { 'build, then start the packaged app' } else { 'packaged app' }
$script:StepCount = if ($Dev) { 6 } elseif ($Build) { 8 } else { 4 }
try {
    Write-Host '================================================='
    Write-Host '  PDF Validation - launcher'
    Write-Host ('  Session : ' + $SessionId)
    Write-Host ('  Logs    : ' + $LogRoot)
    Write-Host ('  Mode    : ' + $mode + $(if ($CheckOnly) { ', check only (nothing is installed or started)' } else { '' }))
    Write-Host '================================================='
    Write-Log 'INFO' 'launcher.started' ([ordered]@{ root = $Root; mode = $mode; check_only = [bool]$CheckOnly; user = $env:USERNAME })
    if ($Dev -and $Build) { Stop-Launch 'Choose either -Dev or -Build.' '' 'Run run.bat -Dev to work from source, or run.bat -Build to build and start the packaged app.' }

    if (-not $CheckOnly) {
        $mutex = New-Object System.Threading.Mutex($false, 'Local\PdfValidationDesktopLauncher')
        if (-not $mutex.WaitOne(0)) {
            Stop-Launch 'The launcher is already running.' 'Another run.bat window is starting or running PDF Validation.' 'Use that window, or close it and try again.'
        }
        $ownsInstance = $true
    }
    $packagedExe = $null
    if ($Dev -or $Build) {
        Test-ProjectFiles
        Test-Tools
        Initialize-Python
        Initialize-Frontend
    }
    if ($Dev) {
        Test-Instances
    } else {
        if ($Build) {
            if ($CheckOnly) { [void]$script:Pending.Add('Build the packaged app (npm run build)') } else { Build-PackagedApp }
            $script:StepOffset = 4
        }
        $packagedExe = Find-PackagedApp
        if ($packagedExe) {
            Test-PackagedFiles $packagedExe
            Test-PackagedInstance $packagedExe
        }
    }

    if ($CheckOnly) {
        Write-Host ''
        if ($script:Pending.Count -gt 0) {
            Write-Host '  Check finished. Setup that run.bat would do or that you need to do:' -ForegroundColor Yellow
            foreach ($item in $script:Pending) { Write-Host ('    - ' + $item) }
        } else {
            Write-Host '  Check finished. Everything is ready; run.bat will start the app.' -ForegroundColor Green
        }
        Write-Log 'INFO' 'launcher.check_finished' ([ordered]@{ pending = $script:Pending.Count })
    } else {
        $appExit = if ($Dev) { Start-Application 'npm run dev' $Root } else { Start-Application ('"' + $packagedExe + '"') $script:AppDir }
        Write-Log 'INFO' 'app.closed' ([ordered]@{ exit_code = $appExit })
        Start-Sleep -Milliseconds 800
        if ($appExit -ne 0) {
            $exitCode = 1
            Show-Failure ('The app closed with an error (exit code {0}).' -f $appExit) ((Get-SessionErrors) + "`r`n`r`n" + (Get-AppOutput 12)) 'Open the logs folder for the complete details.'
            $script:Reported = $true
        } else {
            $clean = Test-SessionEvent 'event=backend\.stopped .*graceful=true'
            Write-Host ''
            Write-Host '  PDF Validation closed.' -ForegroundColor Green
            if ($clean) { Show-Info 'The validation engine was shut down cleanly.' } else {
                Show-Warn 'The validation engine shutdown was not confirmed in the log. See application.log.'
                Write-Log 'WARNING' 'launcher.backend_shutdown_unconfirmed'
            }
        }
    }
} catch {
    $exitCode = 1
    if (-not $script:Reported) {
        $message = $_.Exception.Message
        Write-Log 'ERROR' 'launcher.unexpected_error' ([ordered]@{ error = $_.Exception.GetType().Name; reason = $message; where = $_.ScriptStackTrace })
        Show-Failure 'The launcher hit an unexpected problem.' $message 'Send the logs folder to the maintainer.'
    }
} finally {
    if ($script:AppProcess -and -not $script:AppProcess.HasExited) { Stop-Tree $script:AppProcess.Id }
    if ($ownsInstance) { try { Stop-LeftoverProcesses } catch { } }
    if ($mutex) { if ($ownsInstance) { try { $mutex.ReleaseMutex() } catch { } }; $mutex.Dispose() }
    Write-Log 'INFO' 'launcher.stopped' ([ordered]@{ exit_code = $exitCode })
}
exit $exitCode
