param(
    [string]$DestinationDirectory = [Environment]::GetFolderPath('Desktop')
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$launcherPath = Join-Path $projectRoot '启动项目.cmd'
$helperPath = Join-Path $projectRoot 'scripts\launch_apps.py'
if (!(Test-Path -LiteralPath $launcherPath -PathType Leaf) -or
    !(Test-Path -LiteralPath $helperPath -PathType Leaf)) {
    throw '项目启动文件不完整，请在完整项目目录中运行此脚本。'
}
$destination = (Resolve-Path -LiteralPath $DestinationDirectory).Path
if (!(Test-Path -LiteralPath $destination -PathType Container)) {
    throw '快捷方式保存位置必须是已存在的文件夹。'
}
$shortcutPath = Join-Path $destination '小栗摄影助手（双页面）.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if (Test-Path -LiteralPath $shortcutPath) {
    if ($shortcut.TargetPath -ne $launcherPath -or $shortcut.Arguments -ne '') {
        throw '已存在不同设置的同名快捷方式，未覆盖，请先选择其他保存文件夹。'
    }
    Write-Output "快捷方式已存在，保留原设置：$shortcutPath"
    exit 0
}
$shortcut.TargetPath = $launcherPath
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Arguments = ''
$shortcut.Description = '启动小栗拍摄助手和知识库导入工作台'
$shortcut.WindowStyle = 1
$shortcut.Save()
Write-Output "已创建快捷方式：$shortcutPath"
