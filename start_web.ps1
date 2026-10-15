param(
    [switch]$CheckOnly,
    [switch]$NoBrowser,
    [int]$Port = 8080
)

$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskLegacyRoot = Join-Path (Split-Path -Parent $taskRoot) 'xiaoli-camera-assistant'
$taskRuntime = Join-Path $taskRoot '.launcher'
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    $taskPython = Join-Path $taskLegacyRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw '找不到应用 Python 环境。' }
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'mobile\dist\index.html'))) {
    throw '网页尚未构建，请先执行 npm --prefix mobile run build。'
}
New-Item -ItemType Directory -Path $taskRuntime -Force | Out-Null
$taskPackages = Join-Path $taskRuntime 'python-packages'
$taskTemporaryPackages = Join-Path $taskRoot '.tmp\api-deps'
if (-not (Test-Path -LiteralPath (Join-Path $taskPackages 'fastapi')) -and
    (Test-Path -LiteralPath (Join-Path $taskTemporaryPackages 'fastapi'))) {
    New-Item -ItemType Directory -Path $taskPackages -Force | Out-Null
    Get-ChildItem -LiteralPath $taskTemporaryPackages | Copy-Item -Destination $taskPackages -Recurse
}
$env:PYTHONPATH = $taskPackages + ';' + (Join-Path $taskRoot 'src')
$env:PYTHONUTF8 = '1'
$taskEntry = Join-Path $taskRoot 'scripts\local_web.py'
$taskCheckOutput = & $taskPython -X utf8 $taskEntry --check --resource-root $taskLegacyRoot
if ($LASTEXITCODE -ne 0) { throw '配置检查失败，请检查模型凭据与运行环境。' }
$taskExpected = $taskCheckOutput | ConvertFrom-Json

function Get-LocalStatus([int]$TaskPort) {
    try {
        return Invoke-RestMethod -Uri ('http://127.0.0.1:{0}/local-status' -f $TaskPort) -TimeoutSec 2
    } catch { return $null }
}
function Test-LocalPort([int]$TaskPort) {
    $taskTcp = New-Object System.Net.Sockets.TcpClient
    try { $taskTcp.Connect('127.0.0.1', $TaskPort); return $true } catch { return $false }
    finally { $taskTcp.Dispose() }
}
function Test-LocalIdentity($TaskActual, $TaskSaved) {
    return ($TaskActual -and $TaskSaved -and
        $TaskActual.service -eq 'xiaoli-desktop-web' -and
        $TaskActual.project_root -eq $taskRoot -and $TaskSaved.project_root -eq $taskRoot -and
        $TaskActual.build_id -eq $taskExpected.build_id -and $TaskSaved.build_id -eq $taskExpected.build_id -and
        $TaskActual.configuration_id -eq $taskExpected.configuration_id -and
        $TaskSaved.configuration_id -eq $taskExpected.configuration_id -and
        $TaskActual.launch_id -eq $TaskSaved.launch_id -and
        $TaskActual.pid -eq $TaskSaved.pid)
}
# Serialize launchers for this checkout so a second click cannot overwrite the
# private startup link while the first process is still binding its port.
$taskHasher = [System.Security.Cryptography.SHA256]::Create()
try {
    $taskHash = $taskHasher.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($taskRoot.ToLowerInvariant()))
    $taskMutexName = 'Local\XiaoliWeb-' + ([BitConverter]::ToString($taskHash).Replace('-', '').Substring(0, 20))
} finally { $taskHasher.Dispose() }
$taskMutex = New-Object System.Threading.Mutex($false, $taskMutexName)
$taskMutexOwned = $false
try {
    try { $taskMutexOwned = $taskMutex.WaitOne(45000) }
    catch [System.Threading.AbandonedMutexException] { $taskMutexOwned = $true }
    if (-not $taskMutexOwned) { throw '另一个启动器仍在准备网页，请稍后重试。' }
    $taskStatePath = Join-Path $taskRuntime 'web-start.json'
    $taskState = $null
    if (Test-Path -LiteralPath $taskStatePath) {
        try {
            $taskSaved = Get-Content -LiteralPath $taskStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $taskSavedPort = ([Uri]$taskSaved.url).Port
            $taskActual = Get-LocalStatus $taskSavedPort
            if (Test-LocalIdentity $taskActual $taskSaved) {
                $taskState = $taskSaved
            }
        } catch { $taskState = $null }
    }
    if ($CheckOnly) {
        Write-Output ('Project: ' + $taskRoot)
        Write-Output ('Mode: ' + $taskExpected.analysis_mode)
        Write-Output ('Ready: ' + [bool]$taskState)
        if ($taskState) { Write-Output ('URL: ' + $taskState.url) }
        return
    }
    if (-not $taskState) {
        if ($Port -lt 1024 -or $Port -gt 65525) { throw '端口需为 1024–65525。' }
        $taskChosenPort = $Port
        while (Test-LocalPort $taskChosenPort) {
            $taskChosenPort++
            if ($taskChosenPort -gt $Port + 10) { throw '附近端口已占用，请指定其他端口。' }
        }
        $taskLaunchId = [Guid]::NewGuid().ToString('N')
        $taskArgs = '-X utf8 "{0}" --port {1} --resource-root "{2}" --launch-id {3}' -f $taskEntry, $taskChosenPort, $taskLegacyRoot, $taskLaunchId
        $taskErrorLog = Join-Path $taskRuntime ('web-' + $taskLaunchId + '-stderr.log')
        $taskProcess = Start-Process -FilePath $taskPython -ArgumentList $taskArgs -WindowStyle Hidden `
            -WorkingDirectory $taskRoot -PassThru `
            -RedirectStandardOutput (Join-Path $taskRuntime ('web-' + $taskLaunchId + '-stdout.log')) `
            -RedirectStandardError $taskErrorLog
        $taskDeadline = [DateTime]::UtcNow.AddSeconds(40)
        do {
            $taskActual = Get-LocalStatus $taskChosenPort
            if ($taskActual -and $taskActual.service -eq 'xiaoli-desktop-web' -and
                $taskActual.launch_id -eq $taskLaunchId -and $taskActual.build_id -eq $taskExpected.build_id -and
                $taskActual.configuration_id -eq $taskExpected.configuration_id -and
                $taskActual.project_root -eq $taskRoot) {
                $taskSaved = Get-Content -LiteralPath $taskStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
                if (Test-LocalIdentity $taskActual $taskSaved) {
                    $taskState = $taskSaved
                    break
                }
            }
            if ($taskProcess.HasExited -or [DateTime]::UtcNow -gt $taskDeadline) {
                throw ('网页未启动，请查看：' + $taskErrorLog)
            }
            Start-Sleep -Milliseconds 250
        } while ($true)
    }
    if (-not $NoBrowser) { Start-Process -FilePath $taskState.launch_url }
    Write-Output ('小栗新版网页已启动：' + $taskState.url)
    Write-Output ('分析方式：' + $taskState.analysis_mode)
} finally {
    if ($taskMutexOwned) { $taskMutex.ReleaseMutex() }
    $taskMutex.Dispose()
}
