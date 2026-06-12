#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/backend/.env"
ENV_EXAMPLE="$ROOT_DIR/backend/.env.example"
SETUP_VENV="$ROOT_DIR/.setup-venv"

SKIP_OLLAMA=0
SKIP_MODELS=0
SKIP_COMPOSE=0
FORCE_ENV=0
WITH_MARLIN=0
DOCKER_MODELS=0
HOST_AUTOSTART=1
COMPOSE_BUILD=1
INSTALL_DOCKER=0
MIN_FREE_GB=40

usage() {
  cat <<'EOF'
LiveOS setup

Usage:
  ./setup.sh [options]

Options:
  --skip-ollama      Do not install/start Ollama or pull Ollama models
  --skip-models      Do not download Hugging Face models
  --skip-compose     Do not run docker compose
  --no-build         Run docker compose up -d without --build
  --force-env        Rewrite backend/.env with local Ollama Docker defaults
  --with-marlin      Also download the optional Marlin video-visual model
  --docker-models    Force Marlin/local-models to run inside Docker
  --no-host-autostart
                     Start native macOS inference for this session only
  --install-docker   Try to install Docker if it is missing
  --min-free-gb N    Required free disk space before setup starts (default: 40)
  -h, --help         Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-ollama) SKIP_OLLAMA=1 ;;
    --skip-models) SKIP_MODELS=1 ;;
    --skip-compose) SKIP_COMPOSE=1 ;;
    --no-build) COMPOSE_BUILD=0 ;;
    --force-env) FORCE_ENV=1 ;;
    --with-marlin) WITH_MARLIN=1 ;;
    --docker-models) DOCKER_MODELS=1 ;;
    --no-host-autostart) HOST_AUTOSTART=0 ;;
    --install-docker) INSTALL_DOCKER=1 ;;
    --min-free-gb)
      shift
      MIN_FREE_GB="${1:?Missing value for --min-free-gb}"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

if [[ "$(uname -s)" != "Darwin" && "$DOCKER_MODELS" == "0" ]]; then
  DOCKER_MODELS=1
fi

log() {
  printf '\n==> %s\n' "$1"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

require_command() {
  if ! command_exists "$1"; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

check_free_space() {
  local available_kb available_gb
  available_kb="$(df -Pk "$ROOT_DIR" | awk 'NR==2 {print $4}')"
  available_gb="$((available_kb / 1024 / 1024))"
  if (( available_gb < MIN_FREE_GB )); then
    cat >&2 <<EOF
Only ${available_gb}GB free. LiveOS setup downloads ML models and builds Docker
images, so at least ${MIN_FREE_GB}GB free is recommended.

Free more disk space or rerun with --min-free-gb ${available_gb}.
EOF
    exit 1
  fi
}

configure_env() {
  local created=0
  if [[ ! -f "$ENV_FILE" ]]; then
    log "Creating backend/.env"
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    created=1
  fi

  if (( created == 0 && FORCE_ENV == 0 )); then
    echo "backend/.env already exists; leaving it unchanged. Use --force-env to apply Ollama defaults."
    return
  fi

  log "Writing Docker-friendly Ollama defaults to backend/.env"
  python3 - "$ENV_FILE" \
    LLM_PROVIDER=ollama \
    LLM_BASE_URL=http://host.docker.internal:11434 \
    LLM_API_KEY=ollama \
    CHAT_MODEL=gemma4:e4b \
    INGESTION_PROVIDER=ollama \
    INGESTION_BASE_URL=http://host.docker.internal:11434 \
    INGESTION_API_KEY=ollama \
    INGESTION_MODEL=gemma4:e4b \
    EMBEDDING_PROVIDER=ollama \
    EMBEDDING_BASE_URL=http://host.docker.internal:11434 \
    EMBEDDING_API_KEY=ollama \
    EMBEDDING_MODEL=qwen3-embedding:0.6b \
    MARLIN_SERVICE_URL=http://host.docker.internal:8790 \
    LOCAL_MODELS_SERVICE_URL=http://host.docker.internal:8791 <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
updates = dict(arg.split("=", 1) for arg in sys.argv[2:])
lines = path.read_text().splitlines()
seen = set()
out = []

for line in lines:
    stripped = line.lstrip()
    prefix = line[: len(line) - len(stripped)]
    active = stripped
    commented = False
    if stripped.startswith("#"):
        commented = True
        active = stripped[1:].lstrip()
    if "=" in active:
        key = active.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{prefix}{key}={updates[key]}")
            seen.add(key)
            continue
    out.append(line)

missing = [key for key in updates if key not in seen]
if missing:
    out.append("")
    out.append("# Added by setup.sh")
    for key in missing:
        out.append(f"{key}={updates[key]}")

path.write_text("\n".join(out) + "\n")
PY
}

install_ollama() {
  if (( SKIP_OLLAMA == 1 )); then
    return
  fi

  if command_exists ollama; then
    echo "Ollama already installed."
    return
  fi

  log "Installing Ollama"
  case "$(uname -s)" in
    Darwin)
      if command_exists brew; then
        brew install ollama
      else
        cat >&2 <<'EOF'
Ollama is not installed and Homebrew was not found.
Install Ollama from https://ollama.com/download, then rerun ./setup.sh.
EOF
        exit 1
      fi
      ;;
    Linux)
      curl -fsSL https://ollama.com/install.sh | sh
      ;;
    *)
      echo "Unsupported Unix platform for automatic Ollama install. Install Ollama manually." >&2
      exit 1
      ;;
  esac
}

start_ollama() {
  if (( SKIP_OLLAMA == 1 )); then
    return
  fi

  log "Starting Ollama"
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama is already running."
    return
  fi

  nohup ollama serve >"$ROOT_DIR/.ollama.log" 2>&1 &
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      echo "Ollama started."
      return
    fi
    sleep 1
  done

  echo "Ollama did not start within 30 seconds. Check .ollama.log." >&2
  exit 1
}

pull_ollama_models() {
  if (( SKIP_OLLAMA == 1 )); then
    return
  fi

  log "Pulling Ollama models"
  ollama pull gemma4:e4b
  ollama pull qwen3-embedding:0.6b
}

install_docker_if_requested() {
  if command_exists docker; then
    return
  fi

  if (( INSTALL_DOCKER == 0 )); then
    cat >&2 <<'EOF'
Docker is not installed or not on PATH.
Install Docker Desktop from https://www.docker.com/products/docker-desktop/
or rerun setup with --install-docker.
EOF
    exit 1
  fi

  log "Installing Docker"
  case "$(uname -s)" in
    Darwin)
      if command_exists brew; then
        brew install --cask docker
        cat <<'EOF'
Docker Desktop was installed. Open Docker Desktop and wait for it to finish
starting, then rerun ./setup.sh.
EOF
        exit 0
      fi
      echo "Homebrew is required for automatic Docker Desktop install on macOS." >&2
      exit 1
      ;;
    Linux)
      curl -fsSL https://get.docker.com | sh
      cat <<'EOF'
Docker Engine was installed. You may need to log out and back in, or run:
  sudo usermod -aG docker "$USER"
Then rerun ./setup.sh.
EOF
      exit 0
      ;;
    *)
      echo "Unsupported Unix platform for automatic Docker install." >&2
      exit 1
      ;;
  esac
}

download_hf_models() {
  if (( SKIP_MODELS == 1 )); then
    return
  fi

  require_command python3
  log "Preparing Hugging Face downloader"
  python3 -m venv "$SETUP_VENV"
  # shellcheck source=/dev/null
  source "$SETUP_VENV/bin/activate"
  python -m pip install --upgrade pip
  python -m pip install --upgrade "huggingface_hub[cli]"

  log "Downloading local multimedia/reranker models"
  huggingface-cli download microsoft/Florence-2-large \
    --local-dir "$ROOT_DIR/backend/models/florence-2-large"
  huggingface-cli download openai/whisper-large-v3-turbo \
    --local-dir "$ROOT_DIR/backend/models/whisper-large-v3-turbo"
  huggingface-cli download Qwen/Qwen3-Reranker-0.6B \
    --local-dir "$ROOT_DIR/backend/models/qwen3-reranker-0.6b"

  if (( WITH_MARLIN == 1 )); then
    huggingface-cli download NemoStation/Marlin-2B \
      --local-dir "$ROOT_DIR/backend/models/marlin-2b"
  fi
}

run_compose() {
  if (( SKIP_COMPOSE == 1 )); then
    return
  fi

  install_docker_if_requested
  log "Checking Docker"
  docker info >/dev/null

  log "Starting LiveOS Docker stack"
  if (( COMPOSE_BUILD == 1 )); then
    if (( DOCKER_MODELS == 1 )); then
      docker compose --profile docker-models up -d --build
    else
      docker compose up -d --build
    fi
  else
    if (( DOCKER_MODELS == 1 )); then
      docker compose --profile docker-models up -d
    else
      docker compose up -d
    fi
  fi
}

start_host_inference() {
  if (( SKIP_COMPOSE == 1 || DOCKER_MODELS == 1 )); then
    return
  fi

  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Native host inference is only used on macOS. Model services are running through Docker."
    return
  fi

  if (( HOST_AUTOSTART == 1 )); then
    log "Enabling native macOS inference auto-start (Marlin + local-models)"
    "$ROOT_DIR/scripts/host-inference.sh" enable
  else
    log "Starting native macOS inference services for this session"
    "$ROOT_DIR/scripts/host-inference.sh" start
  fi
}

main() {
  cd "$ROOT_DIR"
  require_command curl
  require_command python3
  check_free_space
  configure_env
  install_ollama
  start_ollama
  pull_ollama_models
  download_hf_models
  run_compose
  start_host_inference

  cat <<'EOF'

LiveOS setup complete.
Open http://localhost:3700

Useful checks:
  docker compose ps
  docker compose logs init
  docker compose logs backend
  tail -f .host-inference-logs/marlin.log
  tail -f .host-inference-logs/local-models.log
  ./scripts/host-inference.sh status
  ./scripts/host-inference.sh disable
EOF
}

main
