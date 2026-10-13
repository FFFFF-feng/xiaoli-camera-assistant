param(
    [string]$Python = "",
    [ValidateSet("all", "grounding_dino", "yolo26")][string]$Detector = "all",
    [string]$Revision = "main",
    [switch]$ProbeOnly,
    [switch]$ReinstallTorch,
    [string]$TorchIndex = "https://download.pytorch.org/whl/cpu"
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$detectorEnv = Join-Path $projectRoot ".venv-detectors"
$detectorPython = Join-Path $detectorEnv "Scripts\python.exe"
Set-Location -LiteralPath $projectRoot

# Select an existing interpreter. Never delete or rebuild the original .venv.
if (-not $Python) {
    $existingPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $existingPython) { $Python = $existingPython }
    else { $Python = "python" }
}
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCommand) {
    if (-not (Test-Path -LiteralPath $detectorPython)) {
        & $uvCommand.Source venv --python $Python $detectorEnv
        if ($LASTEXITCODE) { throw "创建独立检测环境失败。" }
    }
    $torchArguments = @("pip", "install", "--python", $detectorPython, "--index-url", $TorchIndex, "torch==2.10.0", "torchvision==0.25.0")
    if ($ReinstallTorch) { $torchArguments += @("--reinstall-package", "torch", "--reinstall-package", "torchvision") }
    & $uvCommand.Source @torchArguments
    if ($LASTEXITCODE) { throw "PyTorch 安装失败；检查网络及所选 Python 的 wheel 支持。" }
    & $uvCommand.Source pip install --python $detectorPython -r (Join-Path $projectRoot "requirements-detectors.txt")
} else {
    if (-not (Test-Path -LiteralPath $detectorPython)) {
        & $Python -m venv $detectorEnv
        if ($LASTEXITCODE) { throw "venv/ensurepip 失败；安装 uv 后重试，或显式指定兼容的 -Python。" }
    }
    $torchArguments = @("-m", "pip", "install", "--index-url", $TorchIndex, "torch==2.10.0", "torchvision==0.25.0")
    if ($ReinstallTorch) { $torchArguments += "--force-reinstall" }
    & $detectorPython @torchArguments
    if ($LASTEXITCODE) { throw "PyTorch 安装失败。" }
    & $detectorPython -m pip install -r (Join-Path $projectRoot "requirements-detectors.txt")
}
if ($LASTEXITCODE) { throw "检测依赖安装失败。" }
$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:PYTHONUTF8 = "1"
$env:HF_HUB_DISABLE_IMPLICIT_TOKEN = "1"
$env:YOLO_AUTOINSTALL = "false"
$env:YOLO_CONFIG_DIR = Join-Path $projectRoot "data\vision_lab\model_cache\ultralytics"
$arguments = @("-m", "vision_lab_tool.detectors.prepare", "--detector", $Detector, "--revision", $Revision)
if ($ProbeOnly) { $arguments += "--probe-only" }
& $detectorPython @arguments
if ($LASTEXITCODE) { throw "权重准备失败；保留已下载文件，可重试明确的准备操作。" }
Write-Host "检测准备完成。原 Streamlit 环境未安装检测框架。"
