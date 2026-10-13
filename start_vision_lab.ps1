param(
    [switch]$CheckOnly,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$labProjectPath = $PSScriptRoot
$labPythonPath = Join-Path $labProjectPath '.venv\Scripts\python.exe'
$labEntryPath = Join-Path $labProjectPath 'vision_lab.py'
$labPageUrl = 'http://127.0.0.1:8502/'
$labHealthUrl = 'http://127.0.0.1:8502/_stcore/health'

function Test-VisionLabReady {
    try {
        $labHealth = Invoke-WebRequest -Uri $labHealthUrl -UseBasicParsing -TimeoutSec 2
        return ($labHealth.StatusCode -eq 200 -and $labHealth.Content.Trim() -eq 'ok')
    }
    catch {
        return $false
    }
}

try {
    if (-not (Test-Path -LiteralPath $labPythonPath -PathType Leaf)) {
        throw '找不到项目虚拟环境。请按 docs\vision-lab.md 的首次安装步骤安装依赖。'
    }
    if (-not (Test-Path -LiteralPath $labEntryPath -PathType Leaf)) {
        throw '找不到 vision_lab.py，请保留项目目录和启动脚本的位置。'
    }

    if ($CheckOnly) {
        Write-Output ('Project: ' + $labProjectPath)
        Write-Output ('Ready: ' + (Test-VisionLabReady))
        Write-Output ('URL: ' + $labPageUrl)
        exit 0
    }

    if (-not (Test-VisionLabReady)) {
        $labLogDirectory = Join-Path $labProjectPath 'data\vision_lab\launcher'
        New-Item -ItemType Directory -Path $labLogDirectory -Force | Out-Null
        $labArguments = '-m streamlit run "{0}" --server.port 8502 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false' -f $labEntryPath
        $labProcess = Start-Process -FilePath $labPythonPath -ArgumentList $labArguments `
            -WorkingDirectory $labProjectPath -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $labLogDirectory 'stdout.log') `
            -RedirectStandardError (Join-Path $labLogDirectory 'stderr.log')

        $labDeadline = [DateTime]::UtcNow.AddSeconds(40)
        while (-not (Test-VisionLabReady)) {
            if ($labProcess.HasExited -or [DateTime]::UtcNow -gt $labDeadline) {
                throw ('工具未能启动，8502 端口可能被占用。诊断日志：' + $labLogDirectory)
            }
            Start-Sleep -Milliseconds 400
        }
    }

    if (-not $NoBrowser) {
        Start-Process -FilePath $labPageUrl
    }
}
catch {
    if ($CheckOnly -or $NoBrowser) {
        Write-Error $_.Exception.Message
        exit 1
    }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '小栗视觉模型测试') | Out-Null
    exit 1
}
