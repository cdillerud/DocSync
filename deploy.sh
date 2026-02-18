#!/bin/bash
# GPI Document Hub - VM Deployment Script
# Run this on the target VM after copying the bundle

set -e

echo "=== GPI Document Hub Deployment ==="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "Docker installed. Please log out and back in, then run this script again."
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
    echo "ERROR: backend/.env not found!"
    echo "Copy backend/.env.example to backend/.env and fill in your values."
    echo ""
    exit 1
fi

# Build and start services
echo ""
echo "Building and starting services..."
sudo docker compose up -d --build

# Wait for services to be healthy
echo ""
echo "Waiting for services to start..."
sleep 10

# Check status
echo ""
echo "=== Service Status ==="
sudo docker compose ps

echo ""
echo "=== Checking API Health ==="
curl -s http://localhost/api/health || echo "API not responding yet, give it a moment..."

echo ""
echo "=== Deployment Complete ==="
echo "Access the application at: http://$(hostname -I | awk '{print $1}')"
echo ""
echo "Useful commands:"
echo "  View logs:    sudo docker compose logs -f"
echo "  Stop:         sudo docker compose down"
echo "  Restart:      sudo docker compose restart"
echo "  Rebuild:      sudo docker compose up -d --build"
