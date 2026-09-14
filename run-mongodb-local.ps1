<#
.SYNOPSIS
    Runs a local, per-user MongoDB instance for this project without Docker,
    without installing anything system-wide, and without administrator rights.

.DESCRIPTION
    Downloads the official MongoDB Community Server ZIP (not the MSI installer,
    which is the one that requires admin rights to register a Windows service),
    extracts it under your own user profile, and starts mongod as a normal
    foreground process bound to 127.0.0.1:27017 — the same address the app's
    default MONGODB_URI already expects. No WSL, no Hyper-V, no Docker.

.PARAMETER Version
    MongoDB Community Server version to download. Defaults to 7.0.14 (matches
    this project's docker-compose.yml, which uses the mongo:7 image).

.EXAMPLE
    .\run-mongodb-local.ps1
    Downloads MongoDB on first run (if not already present), then starts it.
    Leave this window open while you use the app; press Ctrl+C to stop it.
#>

param(
    [string]$Version = "7.0.14"
)

$ErrorActionPreference = "Stop"

$MongoRoot = Join-Path $env:USERPROFILE "mongodb"
$DataDir = Join-Path $MongoRoot "data"
$ZipPath = Join-Path $MongoRoot "mongodb.zip"

New-Item -ItemType Directory -Force -Path $MongoRoot | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$ExistingInstall = Get-ChildItem -Path $MongoRoot -Directory -Filter "mongodb-*" -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $ExistingInstall) {
    $Url = "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-$Version.zip"
    Write-Host "Downloading MongoDB Community Server $Version (no install, no admin required)..."
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath

    Write-Host "Extracting to $MongoRoot ..."
    Expand-Archive -Path $ZipPath -DestinationPath $MongoRoot -Force
    Remove-Item $ZipPath

    $ExistingInstall = Get-ChildItem -Path $MongoRoot -Directory -Filter "mongodb-*" | Select-Object -First 1
}

$MongodExe = Join-Path $ExistingInstall.FullName "bin\mongod.exe"

if (-not (Test-Path $MongodExe)) {
    throw "Could not find mongod.exe under $($ExistingInstall.FullName)\bin. Delete $MongoRoot and re-run this script."
}

Write-Host "Starting MongoDB on 127.0.0.1:27017 (data dir: $DataDir)"
Write-Host "Leave this window open. Press Ctrl+C to stop MongoDB."

& $MongodExe --dbpath $DataDir --port 27017 --bind_ip 127.0.0.1
