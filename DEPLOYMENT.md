# GPI Document Hub - Deployment Guide

## Quick Start

### 1. Copy to VM
```bash
scp -r ./gpi-hub azureuser@4.204.41.190:/opt/gpi-hub
```

### 2. SSH to VM
```bash
ssh azureuser@4.204.41.190
cd /opt/gpi-hub
```

### 3. Configure Environment
```bash
cp backend/.env.example backend/.env
nano backend/.env  # Fill in your values
```

### 4. Deploy
```bash
chmod +x deploy.sh
./deploy.sh
```

### 5. Access
Open http://4.204.41.190 in your browser.

---

## Configuration

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `TENANT_ID` | Azure AD tenant ID |
| `BC_CLIENT_ID` | Business Central app client ID |
| `BC_CLIENT_SECRET` | Business Central app secret |
| `GRAPH_CLIENT_ID` | Graph API app client ID |
| `GRAPH_CLIENT_SECRET` | Graph API app secret |
| `SHAREPOINT_SITE_HOSTNAME` | e.g., `yourcompany.sharepoint.com` |
| `SHAREPOINT_SITE_PATH` | e.g., `/sites/DocumentHub` |
| `JWT_SECRET` | Strong random secret for auth |
| `EMERGENT_LLM_KEY` | Emergent LLM key for AI classification |

### Optional Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `DEMO_MODE` | `false` | Enable demo mode (mock APIs) |
| `ENABLE_CREATE_DRAFT_HEADER` | `false` | Enable BC draft creation |
| `EMAIL_POLLING_ENABLED` | `false` | Enable email polling |
| `EMAIL_POLLING_USER` | | AP inbox email address |

---

## Operations

### View Logs
```bash
sudo docker compose logs -f
sudo docker compose logs -f backend  # Backend only
sudo docker compose logs -f frontend # Frontend only
```

### Restart Services
```bash
sudo docker compose restart
sudo docker compose restart backend  # Backend only
```

### Stop All Services
```bash
sudo docker compose down
```

### Rebuild After Code Changes
```bash
sudo docker compose up -d --build
```

### Check MongoDB
```bash
sudo docker exec -it gpi-mongodb mongosh gpi_document_hub
```

---

## Troubleshooting

### API Not Responding
```bash
# Check backend logs
sudo docker compose logs backend

# Check if container is running
sudo docker compose ps

# Restart backend
sudo docker compose restart backend
```

### MongoDB Connection Issues
```bash
# Check MongoDB status
sudo docker exec -it gpi-mongodb mongosh --eval "db.adminCommand('ping')"

# Restart MongoDB
sudo docker compose restart mongodb
```

### Frontend Not Loading
```bash
# Check nginx logs
sudo docker compose logs frontend

# Verify build
sudo docker compose exec frontend ls -la /usr/share/nginx/html
```

---

## Security Notes

1. **Firewall**: Only port 80 is exposed externally
2. **MongoDB**: Only accessible within Docker network
3. **Backend**: Only accessible via nginx proxy
4. **Secrets**: Never commit `.env` to git

---

## Architecture

```
Internet → :80 (nginx) → Frontend (React)
                      → /api/* → Backend (FastAPI) → MongoDB
```

All services run in isolated Docker containers on a private network.
