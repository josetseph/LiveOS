param(
    [switch]$Yes,
    [switch]$KeepData,
    [switch]$RemoveData,
    [switch]$KeepImages,
    [switch]$KeepHfModels,
    [switch]$KeepOllamaModels,
    [switch]$RemoveAllOllamaModels,
    [switch]$UninstallOllama
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-OllamaPath {
    $cmd = Get-Command "ollama" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Confirm-Teardown {
    if ($Yes) {
        return
    }

    $dataAction = if ($RemoveData -and -not $KeepData) { "will be deleted" } else { "will be kept" }
    $imageAction = if ($KeepImages) { "will be kept" } else { "will be removed" }
    $ollamaAction = if ($UninstallOllama) { "will be uninstalled if possible" } else { "will be kept" }
    $allOllamaModels = if ($RemoveAllOllamaModels) { "will be deleted" } else { "will be kept, except project models if enabled" }

    Write-Host "This will remove the LiveOS Docker stack and downloaded LiveOS models."
    Write-Host ""
    Write-Host "Project data directory: $dataAction"
    Write-Host "Docker images:          $imageAction"
    Write-Host "Ollama app:             $ollamaAction"
    Write-Host "All Ollama models:      $allOllamaModels"
    Write-Host ""
    $answer = Read-Host "Continue? [y/N]"
    if ($answer -notin @("y", "Y", "yes", "YES")) {
        Write-Host "Aborted."
        exit 0
    }
}

function Remove-ComposeStack {
    if (-not (Test-Command "docker")) {
        Write-Host "Docker not found; skipping Docker cleanup."
        return
    }

    Write-Step "Removing Docker containers and networks"
    Set-Location $RootDir
    if ($KeepImages) {
        docker compose down --remove-orphans
    } else {
        docker compose down --remove-orphans --rmi local
    }
}

function Remove-ProjectModels {
    if ($KeepHfModels) {
        return
    }

    Write-Step "Removing Hugging Face models downloaded into backend\models"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $RootDir "backend\models")
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $RootDir ".setup-venv")
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $RootDir ".ollama.log")
}

function Remove-DataDirectory {
    if (-not $RemoveData -or $KeepData) {
        return
    }

    Write-Step "Removing local database/storage data"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $RootDir "data")
}

function Remove-OllamaModels {
    if ($KeepOllamaModels -and -not $RemoveAllOllamaModels) {
        return
    }

    if ($RemoveAllOllamaModels) {
        Write-Step "Removing all Ollama model blobs"
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $env:USERPROFILE ".ollama\models")
        return
    }

    $ollama = Get-OllamaPath
    if (-not $ollama) {
        Write-Host "Ollama not found; skipping Ollama model removal."
        return
    }

    Write-Step "Removing Ollama models used by LiveOS"
    & $ollama rm gemma4:e4b 2>$null
    & $ollama rm qwen3-embedding:0.6b 2>$null
}

function Uninstall-Ollama {
    if (-not $UninstallOllama) {
        return
    }

    Write-Step "Uninstalling Ollama where possible"
    if (Test-Command "winget") {
        winget uninstall --id Ollama.Ollama --source winget --accept-source-agreements
    } else {
        Write-Host "winget is unavailable. Uninstall Ollama manually from Windows Settings."
    }
}

Confirm-Teardown
Remove-ComposeStack
Remove-ProjectModels
Remove-DataDirectory
Remove-OllamaModels
Uninstall-Ollama

Write-Host ""
Write-Host "LiveOS teardown complete."
Write-Host ""
Write-Host "To remove the source code itself, delete this folder:"
Write-Host "  $RootDir"
