#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# AgentOS v0.3 — manual deploy script (run from local machine)
# ============================================================
# Prerequisites: rsync, sshpass (brew install hudochenkov/sshpass/sshpass)
#
# Usage:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh
#
# The script reads server credentials from 资源.md at project root.
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES_FILE="$PROJECT_ROOT/资源.md"

# ── Colours ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'  # No Colour

log_info()  { printf "${BLUE}[INFO]${NC}    %s\n" "$*"; }
log_ok()    { printf "${GREEN}[OK]${NC}      %s\n" "$*"; }
log_warn()  { printf "${YELLOW}[WARN]${NC}    %s\n" "$*"; }
log_error() { printf "${RED}[ERROR]${NC}   %s\n" "$*"; }
log_step()  { printf "\n${BOLD}${BLUE}==> %s${NC}\n" "$*"; }

# ── Parse credentials from 资源.md ───────────────────────────
parse_credentials() {
    if [[ ! -f "$RESOURCES_FILE" ]]; then
        log_error "资源.md not found at $RESOURCES_FILE"
        exit 1
    fi

    # Parse "| SSH | ssh root@47.98.146.98 |" line → host & user
    SSH_LINE=$(grep -E 'SSH.*root@' "$RESOURCES_FILE" | head -1)
    SSH_HOST=$(echo "$SSH_LINE" | perl -ne 'print $1 if /root@([\d.]+)/')
    SSH_USER=$(echo "$SSH_LINE" | perl -ne 'print $1 if /ssh\s+(\w+)@/')

    # Parse "| 密码 | Ry902311 |" line (not "| SMTP 密码 | ...")
    SSH_PASSWORD=$(grep -E '^\| 密码 ' "$RESOURCES_FILE" | head -1 | perl -ne 'print $1 if /\|\s*密码\s*\|\s*(\S+)\s*\|/' 2>/dev/null || true)
    if [[ -z "$SSH_PASSWORD" ]]; then
        # Fallback: grab any non-SMTP 密码 line
        SSH_PASSWORD=$(grep -E '密码' "$RESOURCES_FILE" | grep -v 'SMTP' | head -1 | perl -ne 'print $1 if /\|\s*(\S+)\s*\|/' 2>/dev/null || true)
    fi

    # Manual overrides from env
    SSH_HOST="${SSH_HOST_OVERRIDE:-$SSH_HOST}"
    SSH_USER="${SSH_USER_OVERRIDE:-$SSH_USER}"
    SSH_PASSWORD="${SSH_PASSWORD_OVERRIDE:-$SSH_PASSWORD}"

    if [[ -z "$SSH_HOST" || -z "$SSH_USER" || -z "$SSH_PASSWORD" ]]; then
        log_error "Could not parse SSH credentials from 资源.md"
        log_error "  SSH_HOST=${SSH_HOST:-<missing>}"
        log_error "  SSH_USER=${SSH_USER:-<missing>}"
        log_error "  SSH_PASSWORD=${SSH_PASSWORD:-<missing>}"
        exit 1
    fi
}

REMOTE_PATH="/opt/agentos"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

# ── SSH helper ───────────────────────────────────────────────
run_ssh() {
    sshpass -p "$SSH_PASSWORD" ssh $SSH_OPTS "${SSH_USER}@${SSH_HOST}" "$@"
}

# ── Rsync helper ─────────────────────────────────────────────
run_rsync() {
    sshpass -p "$SSH_PASSWORD" rsync -avz \
        -e "ssh $SSH_OPTS" \
        --exclude='.git' \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        --exclude='.venv' \
        --exclude='venv' \
        --exclude='*.pyc' \
        --exclude='.DS_Store' \
        --exclude='*.log' \
        "$@"
}

# ── Main ─────────────────────────────────────────────────────
main() {
    log_step "Parsing credentials from 资源.md ..."
    parse_credentials
    log_ok "Credentials loaded — user=${SSH_USER}, host=${SSH_HOST}"

    log_step "Checking prerequisites ..."
    if ! command -v rsync &>/dev/null; then
        log_error "rsync is required. Install it: brew install rsync"
        exit 1
    fi
    if ! command -v sshpass &>/dev/null; then
        log_error "sshpass is required. Install it: brew install hudochenkov/sshpass/sshpass"
        exit 1
    fi
    log_ok "rsync + sshpass are available"

    log_step "Creating remote directory structure ..."
    run_ssh "mkdir -p ${REMOTE_PATH}/{go-service,python-service,web/dist,nginx,docker}"
    log_ok "Remote directories ready"

    log_step "Syncing go-service ..."
    run_rsync "$PROJECT_ROOT/go-service/" "${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}/go-service/"
    log_ok "go-service synced"

    log_step "Syncing python-service ..."
    run_rsync "$PROJECT_ROOT/python-service/" "${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}/python-service/"
    log_ok "python-service synced"

    log_step "Building React frontend ..."
    if [[ -d "$PROJECT_ROOT/web/node_modules" ]]; then
        log_info "node_modules exists, skipping npm ci"
    else
        (cd "$PROJECT_ROOT/web" && npm ci)
    fi
    (cd "$PROJECT_ROOT/web" && npm run build)
    log_ok "Frontend built"

    log_step "Syncing web/dist ..."
    run_rsync "$PROJECT_ROOT/web/dist/" "${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}/web/dist/"
    log_ok "web/dist synced"

    log_step "Syncing nginx config ..."
    run_rsync "$PROJECT_ROOT/nginx/" "${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}/nginx/"
    log_ok "nginx config synced"

    log_step "Syncing docker-compose.yml ..."
    run_rsync "$PROJECT_ROOT/docker-compose.yml" "${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}/"
    log_ok "docker-compose.yml synced"

    if [[ -d "$PROJECT_ROOT/docker" ]]; then
        log_step "Syncing docker/ init scripts ..."
        run_rsync "$PROJECT_ROOT/docker/" "${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}/docker/"
        log_ok "docker/ scripts synced"
    fi

    log_step "Rebuilding & restarting containers on server ..."
    run_ssh "
        set -e;
        cd ${REMOTE_PATH};
        echo '--- Stopping containers ---';
        docker compose --profile full down || true;
        echo '--- Building images ---';
        docker compose --profile full build --no-cache;
        echo '--- Starting services ---';
        docker compose --profile full up -d;
        echo '--- Waiting for services (15 s) ---';
        sleep 15;
        echo '--- Container status ---';
        docker compose --profile full ps;
    "
    log_ok "Containers restarted"

    log_step "Health check ..."
    HTTP_CODE=$(run_ssh "curl -sf -o /dev/null -w '%{http_code}' http://localhost:8080/health" 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" ]]; then
        log_ok "Health check passed (HTTP ${HTTP_CODE})"
    else
        log_error "Health check FAILED (HTTP ${HTTP_CODE})"
        exit 1
    fi

    printf "\n${BOLD}${GREEN}============================================${NC}\n"
    printf "${BOLD}${GREEN}  Deploy complete — AgentOS v0.3 is live!${NC}\n"
    printf "${BOLD}${GREEN}  http://knownot.cc (Nginx :3000)${NC}\n"
    printf "${BOLD}${GREEN}============================================${NC}\n"
}

main "$@"
