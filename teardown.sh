#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

YES=0
REMOVE_DATA=0
REMOVE_IMAGES=1
REMOVE_HF_MODELS=1
REMOVE_OLLAMA_MODELS=1
UNINSTALL_OLLAMA=0
REMOVE_ALL_OLLAMA_MODELS=0

usage() {
  cat <<'EOF'
LiveOS teardown

Usage:
  ./teardown.sh [options]

Options:
  -y, --yes                    Do not prompt for confirmation
  --keep-data                  Keep ./data database/storage files
  --remove-data                Delete ./data database/storage files
  --keep-images                Keep LiveOS Docker images
  --keep-hf-models             Keep backend/models
  --keep-ollama-models         Keep the Ollama models this project pulls
  --remove-all-ollama-models   Delete ~/.ollama/models (removes unrelated Ollama models too)
  --uninstall-ollama           Try to uninstall Ollama after removing models
  -h, --help                   Show this help

The script never deletes the project folder itself. After teardown, delete the
repository directory manually if you want to remove the source code too.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes) YES=1 ;;
    --keep-data) REMOVE_DATA=0 ;;
    --remove-data) REMOVE_DATA=1 ;;
    --keep-images) REMOVE_IMAGES=0 ;;
    --keep-hf-models) REMOVE_HF_MODELS=0 ;;
    --keep-ollama-models) REMOVE_OLLAMA_MODELS=0 ;;
    --remove-all-ollama-models) REMOVE_ALL_OLLAMA_MODELS=1 ;;
    --uninstall-ollama) UNINSTALL_OLLAMA=1 ;;
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

log() {
  printf '\n==> %s\n' "$1"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

confirm() {
  if (( YES == 1 )); then
    return
  fi

  cat <<EOF
This will remove the LiveOS Docker stack and downloaded LiveOS models.

Project data directory: $( (( REMOVE_DATA == 1 )) && echo "will be deleted" || echo "will be kept" )
Docker images:          $( (( REMOVE_IMAGES == 1 )) && echo "will be removed" || echo "will be kept" )
Ollama app:             $( (( UNINSTALL_OLLAMA == 1 )) && echo "will be uninstalled if possible" || echo "will be kept" )
All Ollama models:      $( (( REMOVE_ALL_OLLAMA_MODELS == 1 )) && echo "will be deleted" || echo "will be kept, except project models if enabled" )

Continue? [y/N]
EOF
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
}

remove_compose_stack() {
  if ! command_exists docker; then
    echo "Docker not found; skipping Docker cleanup."
    return
  fi

  log "Removing Docker containers and networks"
  cd "$ROOT_DIR"
  if (( REMOVE_IMAGES == 1 )); then
    docker compose down --remove-orphans --rmi local
  else
    docker compose down --remove-orphans
  fi
}

remove_host_inference_service() {
  if [[ ! -x "$ROOT_DIR/scripts/host-inference.sh" ]]; then
    return
  fi

  log "Stopping native host inference"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    "$ROOT_DIR/scripts/host-inference.sh" disable || true
  else
    "$ROOT_DIR/scripts/host-inference.sh" stop || true
  fi
}

remove_project_models() {
  if (( REMOVE_HF_MODELS == 0 )); then
    return
  fi

  log "Removing Hugging Face models downloaded into backend/models"
  rm -rf "$ROOT_DIR/backend/models"
  rm -rf "$ROOT_DIR/.setup-venv" "$ROOT_DIR/.host-inference-venv-marlin" \
    "$ROOT_DIR/.host-inference-venv-local-models" "$ROOT_DIR/.host-inference-logs" \
    "$ROOT_DIR/.host-inference.pids" "$ROOT_DIR/.ollama.log"
}

remove_data_dir() {
  if (( REMOVE_DATA == 0 )); then
    return
  fi

  log "Removing local database/storage data"
  rm -rf "$ROOT_DIR/data"
}

remove_ollama_models() {
  if (( REMOVE_OLLAMA_MODELS == 0 && REMOVE_ALL_OLLAMA_MODELS == 0 )); then
    return
  fi

  if (( REMOVE_ALL_OLLAMA_MODELS == 1 )); then
    log "Removing all Ollama model blobs"
    rm -rf "$HOME/.ollama/models"
    return
  fi

  if ! command_exists ollama; then
    echo "Ollama not found; skipping Ollama model removal."
    return
  fi

  log "Removing Ollama models used by LiveOS"
  ollama rm gemma4:e4b >/dev/null 2>&1 || true
  ollama rm qwen3-embedding:0.6b >/dev/null 2>&1 || true
}

uninstall_ollama() {
  if (( UNINSTALL_OLLAMA == 0 )); then
    return
  fi

  log "Uninstalling Ollama where possible"
  case "$(uname -s)" in
    Darwin)
      if command_exists brew; then
        brew uninstall ollama || true
      else
        echo "Homebrew not found; uninstall Ollama manually from Applications."
      fi
      ;;
    Linux)
      if command_exists systemctl; then
        sudo systemctl stop ollama 2>/dev/null || true
        sudo systemctl disable ollama 2>/dev/null || true
      fi
      sudo rm -f /usr/local/bin/ollama /usr/bin/ollama
      sudo rm -rf /usr/share/ollama
      ;;
    *)
      echo "Unsupported platform for automatic Ollama uninstall."
      ;;
  esac
}

main() {
  confirm
  remove_compose_stack
  remove_host_inference_service
  remove_project_models
  remove_data_dir
  remove_ollama_models
  uninstall_ollama

  cat <<EOF

LiveOS teardown complete.

To remove the source code itself, delete this folder:
  $ROOT_DIR
EOF
}

main
