param([switch]$AcceptAndroidSdkLicense)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if (-not $AcceptAndroidSdkLicense) {
    throw 'Read https://developer.android.com/studio#command-tools and pass -AcceptAndroidSdkLicense only after accepting the SDK license.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $projectRoot '.android-tools'
$downloads = Join-Path $toolRoot 'downloads'
$sdkRoot = Join-Path $toolRoot 'sdk'
New-Item -ItemType Directory -Force -Path $downloads, $sdkRoot | Out-Null
function Get-VerifiedArchive($Url, $File, $Hash) {
    if (-not (Test-Path -LiteralPath $File)) {
        Write-Host "Downloading $Url"
        & curl.exe --fail --location --retry 3 --output $File $Url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    }
    if ((Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash -ne $Hash) {
        throw "SHA256 mismatch: $File. Keep the file for inspection; do not extract it."
    }
}
$javaRoot = Join-Path $toolRoot 'jdk'
if (-not (Get-ChildItem -LiteralPath $javaRoot -Filter java.exe -Recurse -ErrorAction SilentlyContinue)) {
    $jdkHash = (Invoke-RestMethod 'https://corretto.aws/downloads/latest_sha256/amazon-corretto-21-x64-windows-jdk.zip').Trim().Split(' ')[0]
    $jdkZip = Join-Path $downloads 'corretto21.zip'
    Get-VerifiedArchive 'https://corretto.aws/downloads/latest/amazon-corretto-21-x64-windows-jdk.zip' $jdkZip $jdkHash
    Expand-Archive -LiteralPath $jdkZip -DestinationPath $javaRoot -Force
}
$javaExe = Get-ChildItem -LiteralPath $javaRoot -Filter java.exe -Recurse | Select-Object -First 1
$env:JAVA_HOME = Split-Path -Parent (Split-Path -Parent $javaExe.FullName)
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
$env:ANDROID_HOME = $sdkRoot
$env:ANDROID_USER_HOME = Join-Path $toolRoot 'android-user'
$env:GRADLE_USER_HOME = Join-Path $toolRoot 'gradle-cache'
$sdkManager = Join-Path $sdkRoot 'cmdline-tools\latest\bin\sdkmanager.bat'
if (-not (Test-Path -LiteralPath $sdkManager)) {
    $sdkZip = Join-Path $downloads 'commandlinetools.zip'
    Get-VerifiedArchive 'https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip' $sdkZip '90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a'
    $stage = Join-Path $toolRoot 'sdk-stage'
    Expand-Archive -LiteralPath $sdkZip -DestinationPath $stage -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $sdkRoot 'cmdline-tools') | Out-Null
    Move-Item -LiteralPath (Join-Path $stage 'cmdline-tools') -Destination (Join-Path $sdkRoot 'cmdline-tools\latest')
}
# Accept only the licenses needed by these packages, not unrelated emulator/add-on licenses.
1..100 | ForEach-Object { 'y' } | & $sdkManager "--sdk_root=$sdkRoot" 'platform-tools' 'platforms;android-36' 'build-tools;35.0.0' 'build-tools;36.0.0'
if ($LASTEXITCODE -ne 0) { throw 'SDK package installation failed.' }
Write-Host "Android tools ready in $toolRoot. No persistent system settings changed."
