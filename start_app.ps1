param(
    [switch]$CheckOnly,
    [switch]$NoBrowser,
    [int]$Port = 8501
)

$ErrorActionPreference = 'Stop'
$appProjectPath = $PSScriptRoot
$appPythonPath = Join-Path $appProjectPath '.venv\Scripts\python.exe'
$appEntryPath = Join-Path $appProjectPath 'app.py'
$appPageUrl = 'http://127.0.0.1:{0}/' -f $Port
$appHealthUrl = $appPageUrl + '_stcore/health'

function Test-CameraAppReady {
    try {
        $appHealth = Invoke-WebRequest -Uri $appHealthUrl -UseBasicParsing -TimeoutSec 2
        return ($appHealth.StatusCode -eq 200 -and $appHealth.Content.Trim() -eq 'ok')
    }
    catch { return $false }
}

try {
    if (-not (Test-Path -LiteralPath $appPythonPath -PathType Leaf)) {
        throw '找不到 .venv。请按 README 的首次安装步骤准备应用环境。'
    }
    if (-not (Test-Path -LiteralPath $appEntryPath -PathType Leaf)) {
        throw '找不到 app.py，请将启动脚本保留在项目根目录。'
    }
    if ($Port -lt 1024 -or $Port -gt 65535) { throw '端口必须为 1024–65535。' }
    if ($CheckOnly) {
        Write-Output ('Project: ' + $appProjectPath)
        Write-Output ('Ready: ' + (Test-CameraAppReady))
        Write-Output ('URL: ' + $appPageUrl)
        exit 0
    }
    if (-not (Test-CameraAppReady)) {
        $appLogDirectory = Join-Path $appProjectPath 'data\history\app_launcher'
        New-Item -ItemType Directory -Path $appLogDirectory -Force | Out-Null
        $appArguments = '-m streamlit run "{0}" --server.port {1} --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false' -f $appEntryPath, $Port
        $appProcess = Start-Process -FilePath $appPythonPath -ArgumentList $appArguments `
            -WorkingDirectory $appProjectPath -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $appLogDirectory 'stdout.log') `
            -RedirectStandardError (Join-Path $appLogDirectory 'stderr.log')
        $appDeadline = [DateTime]::UtcNow.AddSeconds(40)
        while (-not (Test-CameraAppReady)) {
            if ($appProcess.HasExited -or [DateTime]::UtcNow -gt $appDeadline) {
                throw ('应用未能启动，请检查端口与日志：' + $appLogDirectory)
            }
            Start-Sleep -Milliseconds 400
        }
    }
    if (-not $NoBrowser) { Start-Process -FilePath $appPageUrl }
    Write-Output ('小栗应用已启动：' + $appPageUrl)
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
