param(
    [switch]$SkipOllama,
    [switch]$SkipModels,
    [switch]$SkipCompose,
    [switch]$NoBuild,
    [switch]$ForceEnv,
    [switch]$WithMarlin,
    [switch]$NoDockerModels,
    [switch]$InstallDocker,
    [int]$MinFreeGb = 40
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $RootDir "backend\.env"
$EnvExample = Join-Path $RootDir "backend\.env.example"
$SetupVenv = Join-Path $RootDir ".setup-venv"

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

function Require-Command {
    param([string]$Name)
    if (-not (Test-Command $Name)) {
        throw "Missing required command: $Name"
    }
}

function Get-PythonCommand {
    if (Test-Command "py") {
        return @("py", "-3")
    }
    if (Test-Command "python") {
        return @("python")
    }
    if (Test-Command "python3") {
        return @("python3")
    }
    throw "Python 3 is required. Install it from https://www.python.org/downloads/ and rerun setup.ps1."
}

function Check-FreeSpace {
    $drive = (Get-Item $RootDir).PSDrive
    $availableGb = [math]::Floor($drive.Free / 1GB)
    if ($availableGb -lt $MinFreeGb) {
        throw "Only ${availableGb}GB free. LiveOS setup downloads ML models and builds Docker images; at least ${MinFreeGb}GB free is recommended."
    }
}

function Set-EnvValue {
    param(
        [string]$Path,
        [hashtable]$Updates
    )

    $lines = Get-Content $Path
    $seen = @{}
    $out = New-Object System.Collections.Generic.List[string]

    foreach ($line in $lines) {
        $trimmed = $line.TrimStart()
        $prefixLength = $line.Length - $trimmed.Length
        $prefix = $line.Substring(0, $prefixLength)
        $active = $trimmed
        if ($trimmed.StartsWith("#")) {
            $active = $trimmed.Substring(1).TrimStart()
        }

        if ($active.Contains("=")) {
            $key = $active.Split("=", 2)[0].Trim()
            if ($Updates.ContainsKey($key)) {
                $out.Add("$prefix$key=$($Updates[$key])")
                $seen[$key] = $true
                continue
            }
        }
        $out.Add($line)
    }

    $missing = @($Updates.Keys | Where-Object { -not $seen.ContainsKey($_) })
    if ($missing.Count -gt 0) {
        $out.Add("")
        $out.Add("# Added by setup.ps1")
        foreach ($key in $missing) {
            $out.Add("$key=$($Updates[$key])")
        }
    }

    Set-Content -Path $Path -Value $out -Encoding UTF8
}

function Configure-Env {
    $created = $false
    if (-not (Test-Path $EnvFile)) {
        Write-Step "Creating backend\.env"
        Copy-Item $EnvExample $EnvFile
        $created = $true
    }

    if (-not $created -and -not $ForceEnv) {
        Write-Host "backend\.env already exists; leaving it unchanged. Use -ForceEnv to apply Ollama defaults."
        return
    }

    Write-Step "Writing Docker-friendly Ollama defaults to backend\.env"
    Set-EnvValue -Path $EnvFile -Updates @{
        LLM_PROVIDER = "ollama"
        LLM_BASE_URL = "http://host.docker.internal:11434"
        LLM_API_KEY = "ollama"
        CHAT_MODEL = "gemma4:e4b"
        INGESTION_PROVIDER = "ollama"
        INGESTION_BASE_URL = "http://host.docker.internal:11434"
        INGESTION_API_KEY = "ollama"
        INGESTION_MODEL = "gemma4:e4b"
        EMBEDDING_PROVIDER = "ollama"
        EMBEDDING_BASE_URL = "http://host.docker.internal:11434"
        EMBEDDING_API_KEY = "ollama"
        EMBEDDING_MODEL = "qwen3-embedding:0.6b"
        MARLIN_SERVICE_URL = "http://host.docker.internal:8790"
        LOCAL_MODELS_SERVICE_URL = "http://host.docker.internal:8791"
    }
}

function Install-Ollama {
    if ($SkipOllama) {
        return
    }
    if (Get-OllamaPath) {
        Write-Host "Ollama already installed."
        return
    }
    if (-not (Test-Command "winget")) {
        throw "Ollama is not installed and winget is unavailable. Install Ollama from https://ollama.com/download and rerun setup.ps1."
    }

    Write-Step "Installing Ollama"
    winget install --id Ollama.Ollama --source winget --accept-package-agreements --accept-source-agreements
}

function Start-Ollama {
    if ($SkipOllama) {
        return
    }

    $ollama = Get-OllamaPath
    if (-not $ollama) {
        throw "Ollama was not found after install."
    }

    Write-Step "Starting Ollama"
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
        Write-Host "Ollama is already running."
        return
    } catch {
        Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
    }

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
            Write-Host "Ollama started."
            return
        } catch {
        }
    }

    throw "Ollama did not start within 30 seconds."
}

function Pull-OllamaModels {
    if ($SkipOllama) {
        return
    }

    $ollama = Get-OllamaPath
    if (-not $ollama) {
        throw "Ollama was not found."
    }

    Write-Step "Pulling Ollama models"
    & $ollama pull gemma4:e4b
    & $ollama pull qwen3-embedding:0.6b
}

function Install-DockerIfRequested {
    if (Test-Command "docker") {
        return
    }

    if (-not $InstallDocker) {
        throw "Docker is not installed or not on PATH. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ or rerun setup.ps1 with -InstallDocker."
    }

    if (-not (Test-Command "winget")) {
        throw "winget is unavailable. Install Docker Desktop manually from https://www.docker.com/products/docker-desktop/ and rerun setup.ps1."
    }

    Write-Step "Installing Docker Desktop"
    winget install --id Docker.DockerDesktop --source winget --accept-package-agreements --accept-source-agreements
    Write-Host "Docker Desktop was installed. Start Docker Desktop, wait until it is running, then rerun setup.ps1."
    exit 0
}

function Download-HfModels {
    if ($SkipModels) {
        return
    }

    $python = Get-PythonCommand
    Write-Step "Preparing Hugging Face downloader"
    if ($python.Length -gt 1) {
        & $python[0] $python[1] -m venv $SetupVenv
    } else {
        & $python[0] -m venv $SetupVenv
    }
    $venvPython = Join-Path $SetupVenv "Scripts\python.exe"
    $hfCli = Join-Path $SetupVenv "Scripts\huggingface-cli.exe"

    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install --upgrade "huggingface_hub[cli]"

    Write-Step "Downloading local multimedia/reranker models"
    & $hfCli download microsoft/Florence-2-large --local-dir (Join-Path $RootDir "backend\models\florence-2-large")
    & $hfCli download openai/whisper-large-v3-turbo --local-dir (Join-Path $RootDir "backend\models\whisper-large-v3-turbo")
    & $hfCli download Qwen/Qwen3-Reranker-0.6B --local-dir (Join-Path $RootDir "backend\models\qwen3-reranker-0.6b")

    if ($WithMarlin) {
        & $hfCli download NemoStation/Marlin-2B --local-dir (Join-Path $RootDir "backend\models\marlin-2b")
    }
}

function Run-Compose {
    if ($SkipCompose) {
        return
    }

    Install-DockerIfRequested
    Write-Step "Checking Docker"
    docker info | Out-Null

    Write-Step "Starting LiveOS Docker stack"
    $composeArgs = @("compose")
    if (-not $NoDockerModels) {
        $composeArgs += @("--profile", "docker-models")
    }
    $composeArgs += @("up", "-d")
    if ($NoBuild) {
        docker @composeArgs
    } else {
        docker @($composeArgs + "--build")
    }
}

Set-Location $RootDir
Check-FreeSpace
Configure-Env
Install-Ollama
Start-Ollama
Pull-OllamaModels
Download-HfModels
Run-Compose

Write-Host ""
Write-Host "LiveOS setup complete."
Write-Host "Open http://localhost:3700"
Write-Host ""
Write-Host "Useful checks:"
Write-Host "  docker compose ps"
Write-Host "  docker compose logs init"
Write-Host "  docker compose logs backend"
if (-not $NoDockerModels) {
    Write-Host "  docker compose logs local-models"
    Write-Host "  docker compose logs marlin"
}
