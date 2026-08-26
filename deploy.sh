#!/bin/bash
# GPI Document Hub - VM Deployment Script
# Run this on the target VM after copying/pulling the bundle.
# External cutover readiness requires a separate HTTPS reverse proxy/DNS endpoint.

set -euo pipefail

echo "=== GPI Document Hub Deployment ==="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker "$USER"
    rm get-docker.sh
    echo "Docker installed. Log out/in, then run this script again."
    exit 0
fi

# Check if docker compose is available
if ! docker compose version &> /dev/null; then
    echo "Docker Compose not found. Installing..."
    sudo apt-get update
    sudo apt-get install -y docker-compose-plugin
fi

# Check for .env file
if [ ! -f ./backend/.env ]; then
    echo ""
    echo "ERROR: backend/.env not found."
    echo "Copy backend/.env.example to backend/.env and populate runtime secrets."
    echo ""
    exit 1
fi

# Fail closed on the cutover-critical UAT interlocks before creating containers.
required_env_line() {
    local expected="$1"
    if ! grep -Fqx "$expected" ./backend/.env; then
        echo "ERROR: backend/.env must contain exactly: $expected"
        exit 1
    fi
}

required_env_line 'DEMO_MODE=false'
required_env_line 'BC_READ_ENVIRONMENT=Production'
required_env_line 'BC_WRITE_ENVIRONMENT=Sandbox_NoZetadocs_UAT'
required_env_line 'BC_BLOCK_PRODUCTION_WRITES=true'
required_env_line 'BC_SALES_LINK_WRITE_ENABLED=false'
required_env_line 'SHAREPOINT_TARGET=test'
required_env_line 'SHAREPOINT_BLOCK_PRODUCTION_WRITES=true'
required_env_line 'SALES_EMAIL_POLLING_ENABLED=false'

# Build and start services
echo ""
echo "Building and starting services..."
sudo docker compose up -d --build

# Check status
echo ""
echo "=== Service Status ==="
sudo docker compose ps

# Local-only health proof. Frontend is intentionally bound to loopback:8080.
echo ""
echo "=== Checking Local API Health ==="
health_url='http://127.0.0.1:8080/api/health'
if ! curl --fail --silent --show-error "$health_url"; then
    echo ""
    echo "ERROR: local Hub API health check failed at $health_url"
    echo "Review: sudo docker compose logs backend frontend"
    exit 1
fi
echo ""
echo "Local Hub API health check: PASS"

# External Business Central access must be through a valid HTTPS reverse proxy.
# PUBLIC_HUB_URL should be the API base configured in Business Central, e.g.
# https://hub.example.com/api . Do not put credentials in this variable.
public_hub_url="${PUBLIC_HUB_URL:-}"
if [ -z "$public_hub_url" ]; then
    echo ""
    echo "=== Deployment Started, External UAT Not Yet Proven ==="
    echo "Containers are healthy locally."
    echo "Set PUBLIC_HUB_URL=https://<host>/api after the TLS reverse proxy/DNS endpoint is live,"
    echo "then rerun this script to prove Business Central's external API endpoint."
    exit 0
fi

case "$public_hub_url" in
    https://*/api) ;;
    *)
        echo "ERROR: PUBLIC_HUB_URL must use HTTPS and end exactly in /api"
        exit 1
        ;;
esac

echo ""
echo "=== Checking External HTTPS API Health ==="
if ! curl --fail --silent --show-error "${public_hub_url}/health"; then
    echo ""
    echo "ERROR: external Hub API health check failed at ${public_hub_url}/health"
    echo "Do not configure/approve BC FactBox UAT until HTTPS/DNS/TLS is working."
    exit 1
fi

echo ""
echo "=== Deployment Complete ==="
echo "Local API       : $health_url"
echo "BC Hub API base : $public_hub_url"
echo "AP/Warehouse UAT may proceed. Sales and Inside Sales remain paused."
echo ""
echo "Useful commands:"
echo "  View logs:    sudo docker compose logs -f"
echo "  Stop:         sudo docker compose down"
echo "  Restart:      sudo docker compose restart"
echo "  Rebuild:      sudo docker compose up -d --build"
