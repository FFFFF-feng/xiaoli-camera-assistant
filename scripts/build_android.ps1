param([switch]$SkipNpmInstall)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $projectRoot '.android-tools'
$javaExe = Get-ChildItem -LiteralPath (Join-Path $toolRoot 'jdk') -Filter java.exe -Recurse | Select-Object -First 1
if (-not $javaExe) { throw 'Run scripts/prepare_android.ps1 -AcceptAndroidSdkLicense first.' }
$env:JAVA_HOME = Split-Path -Parent (Split-Path -Parent $javaExe.FullName)
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
$env:ANDROID_HOME = Join-Path $toolRoot 'sdk'
$env:ANDROID_USER_HOME = Join-Path $toolRoot 'android-user'
$env:GRADLE_USER_HOME = Join-Path $toolRoot 'gradle-cache'
# Warm the wrapper cache using the official GitHub release (same distribution/hash).
# The directory key is Gradle's key for the pinned services.gradle.org URL in this repo.
$gradleZip = Join-Path $toolRoot 'downloads\gradle-8.14.3-bin.zip'
$gradleHash = 'bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531'
$wrapperCache = Join-Path $env:GRADLE_USER_HOME 'wrapper\dists\gradle-8.14.3-bin\cv11ve7ro1n3o1j4so8xd9n66'
if (-not (Test-Path -LiteralPath (Join-Path $wrapperCache 'gradle-8.14.3-bin.zip.ok'))) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $gradleZip), $wrapperCache | Out-Null
    if (-not (Test-Path -LiteralPath $gradleZip)) {
        & curl.exe --fail --location --retry 3 --output $gradleZip 'https://github.com/gradle/gradle-distributions/releases/download/v8.14.3/gradle-8.14.3-bin.zip'
        if ($LASTEXITCODE -ne 0) { throw 'Official Gradle download failed.' }
    }
    if ((Get-FileHash -LiteralPath $gradleZip -Algorithm SHA256).Hash -ne $gradleHash) {
        throw 'Gradle SHA256 mismatch; do not use this archive.'
    }
    Copy-Item -LiteralPath $gradleZip -Destination (Join-Path $wrapperCache 'gradle-8.14.3-bin.zip') -Force
}
Push-Location (Join-Path $projectRoot 'mobile')
try {
    if (-not $SkipNpmInstall) {
        & npm.cmd ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Stop any Vite dev server before retrying.' }
    }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Web build failed.' }
    if (-not (Test-Path -LiteralPath 'android')) {
        & npx.cmd cap add android
        if ($LASTEXITCODE -ne 0) { throw 'Android scaffold failed.' }
    }
    & npx.cmd cap sync android
    if ($LASTEXITCODE -ne 0) { throw 'Capacitor sync failed.' }
    Push-Location android
    try {
        & .\gradlew.bat --no-daemon assembleDebug
        if ($LASTEXITCODE -ne 0) { throw 'APK build failed.' }
    } finally { Pop-Location }
    $artifactDir = Join-Path $projectRoot 'output\mobile'
    New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
    $artifact = Join-Path $artifactDir 'xiaoli-camera-assistant-debug.apk'
    Copy-Item -LiteralPath 'android\app\build\outputs\apk\debug\app-debug.apk' -Destination $artifact -Force
    & "$env:ANDROID_HOME\build-tools\36.0.0\apksigner.bat" verify $artifact
    if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
    Write-Host "APK: $artifact"
    Get-FileHash -LiteralPath $artifact -Algorithm SHA256
} finally { Pop-Location }
