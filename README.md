# GPI Document Hub

A middleware hub that orchestrates document ingestion, metadata management, approvals, and attachment linking between Microsoft Dynamics 365 Business Central and SharePoint Online.

## Architecture

```
                    +-------------------+
                    |  GPI Document Hub |
                    |   (FastAPI + React)|
                    +--------+----------+
                             |
              +--------------+--------------+
              |              |              |
     +--------v--+   +------v------+  +----v-------+
     | SharePoint |   | Business    |  | MongoDB    |
     | Online     |   | Central     |  | (Persistence)|
     | (Graph API)|   | (BC API)    |  +------------+
     +------------+   +-------------+
```

## Quick Start

### Prerequisites
- Docker & Docker Compose (for containerized deployment)
- OR Python 3.11+ and Node.js 18+ (for local development)

### 1. Clone and Configure

```bash
cp .env.example backend/.env
# Edit backend/.env with your Entra ID credentials
```

### 2. Run with Docker Compose

```bash
docker-compose up -d
```

### 3. Run Locally

**Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

**Frontend:**
```bash
cd frontend
yarn install
yarn start
```

### 4. Access the Hub

- Frontend: http://localhost:3000
- Backend API: http://localhost:8001/api
- API Docs: http://localhost:8001/docs

### 5. Login

Default test credentials:
- Username: `admin`
- Password: `admin`

## Demo Mode

By default, `DEMO_MODE=true` simulates all Microsoft API calls. This lets you test the full workflow without real credentials.

To connect live services:
1. Register an Entra ID application
2. Grant permissions for Business Central API and Microsoft Graph
3. Configure credentials in `.env`
4. Set `DEMO_MODE=false`

## Features (Phase 1)

- **Document Upload & Link**: Upload PDF/images, store in SharePoint, link to BC Sales Orders
- **Document Queue**: View, filter, and manage documents by status
- **Workflow Engine**: Multi-step orchestration with full audit trail
- **Dashboard**: Real-time stats, charts, and monitoring
- **Dark/Light Theme**: Professional enterprise UI with theme toggle
- **Audit Logging**: Complete workflow run history with step-by-step detail

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/auth/login | Authenticate |
| GET | /api/dashboard/stats | Dashboard statistics |
| POST | /api/documents/upload | Upload & process document |
| GET | /api/documents | List documents |
| GET | /api/documents/{id} | Document detail |
| PUT | /api/documents/{id} | Update document |
| POST | /api/documents/{id}/link | Re-link to BC |
| GET | /api/workflows | List workflow runs |
| POST | /api/workflows/{id}/retry | Retry failed workflow |
| GET | /api/bc/companies | BC companies |
| GET | /api/bc/sales-orders | BC sales orders |
| GET | /api/settings/status | Connection status |

## Phase 2 Roadmap

- Exchange Online email ingestion
- AI-powered document classification (OCR)
- Spiro CRM integration
- Entra SSO for UI
- Document sets mapping

## Tech Stack

- **Backend**: Python, FastAPI, Motor (async MongoDB)
- **Frontend**: React, Tailwind CSS, Shadcn UI, Recharts
- **Database**: MongoDB
- **Auth**: JWT (SSO-ready)
- **APIs**: Microsoft Graph, Business Central API v2.0
