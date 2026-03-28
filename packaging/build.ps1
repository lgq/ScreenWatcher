param(
    [string]$Version = "1.0.0",
    [switch]$SkipInstaller,
    [switch]$SkipPlatformToolsDownload
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildRoot = Join-Path $ProjectRoot "build"
$StagingRoot = Join-Path $BuildRoot "staging"
$DefaultsRoot = Join-Path $StagingRoot "defaults"
$PlatformToolsRoot = Join-Path $StagingRoot "platform-tools"
$DistRoot = Join-Path $ProjectRoot "dist"
$SpecPath = Join-Path $PSScriptRoot "ScreenWatcher.spec"
$InstallerScript = Join-Path $PSScriptRoot "ScreenWatcher.iss"

function Get-PythonExe {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return @{ Path = $venvPython; UsePyLauncher = $false }
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @{ Path = $pythonCmd.Source; UsePyLauncher = $false }
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return @{ Path = $pyCmd.Source; UsePyLauncher = $true }
    }

    throw "Python executable was not found. Install Python or create .venv first."
}

function Invoke-Python {
    param(
        [hashtable]$PythonInfo,
        [string[]]$Arguments
    )

    if ($PythonInfo.UsePyLauncher) {
        & $PythonInfo.Path -3 @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Python command failed with exit code $LASTEXITCODE"
        }
        return
    }

    & $PythonInfo.Path @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

function Reset-BuildFolders {
    foreach ($path in @($StagingRoot, $DistRoot)) {
        if (Test-Path $path) {
            Remove-Item $path -Recurse -Force
        }
    }

    New-Item -ItemType Directory -Force -Path $DefaultsRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $PlatformToolsRoot | Out-Null
}

function Copy-DefaultConfigs {
    foreach ($name in @("settings_config.json", "config.json")) {
        $source = Join-Path $ProjectRoot $name
        if (Test-Path $source) {
            Copy-Item $source $DefaultsRoot -Force
        }
    }

    Get-ChildItem -Path $ProjectRoot -Filter "*_config.json" -File | ForEach-Object {
        Copy-Item $_.FullName $DefaultsRoot -Force
    }

    $appConfigs = Join-Path $ProjectRoot "app_configs"
    if (Test-Path $appConfigs) {
        Copy-Item $appConfigs (Join-Path $DefaultsRoot "app_configs") -Recurse -Force
    }
}

function Ensure-PlatformTools {
    $localPlatformTools = Join-Path $ProjectRoot "platform-tools"
    if (Test-Path (Join-Path $localPlatformTools "adb.exe")) {
        Copy-Item (Join-Path $localPlatformTools "*") $PlatformToolsRoot -Recurse -Force
        return
    }

    if ($SkipPlatformToolsDownload) {
        throw "platform-tools is missing and download is disabled. Prepare platform-tools/adb.exe first."
    }

    $zipPath = Join-Path $BuildRoot "platform-tools-latest-windows.zip"
    $extractRoot = Join-Path $BuildRoot "platform-tools-extract"
    if (Test-Path $extractRoot) {
        Remove-Item $extractRoot -Recurse -Force
    }

    $url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    Write-Host "Downloading Android platform-tools from $url"
    Invoke-WebRequest -Uri $url -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force

    $extracted = Join-Path $extractRoot "platform-tools"
    if (-not (Test-Path (Join-Path $extracted "adb.exe"))) {
        throw "Downloaded platform-tools archive is invalid. adb.exe was not found."
    }

    Copy-Item (Join-Path $extracted "*") $PlatformToolsRoot -Recurse -Force
}

function Ensure-BuildDependencies {
    param([hashtable]$PythonInfo)

    Write-Host "Installing build dependencies..."
    Invoke-Python -PythonInfo $PythonInfo -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Python -PythonInfo $PythonInfo -Arguments @(
        "-m", "pip", "install",
        "pyinstaller",
        "pillow",
        "winrt-runtime",
        "winrt-Windows.Foundation",
        "winrt-Windows.Foundation.Collections",
        "winrt-Windows.Globalization",
        "winrt-Windows.Graphics.Imaging",
        "winrt-Windows.Media.Ocr",
        "winrt-Windows.Storage",
        "winrt-Windows.Storage.Streams"
    )
}

function Build-PyInstaller {
    param([hashtable]$PythonInfo)

    Write-Host "Running PyInstaller..."
    Invoke-Python -PythonInfo $PythonInfo -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", $SpecPath)
}

function Find-ISCC {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Build-Installer {
    $iscc = Find-ISCC
    if (-not $iscc) {
        throw "ISCC.exe was not found. Install Inno Setup 6 first."
    }

    Write-Host "Running Inno Setup..."
    & $iscc "/DAppVersion=$Version" $InstallerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE"
    }
}

$pythonInfo = Get-PythonExe
Write-Host "Using Python: $($pythonInfo.Path)"

Reset-BuildFolders
Copy-DefaultConfigs
Ensure-PlatformTools
Ensure-BuildDependencies -PythonInfo $pythonInfo
Build-PyInstaller -PythonInfo $pythonInfo

if (-not $SkipInstaller) {
    Build-Installer
}

Write-Host "Build finished. Dist directory: $DistRoot"
