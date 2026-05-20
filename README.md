# 🏥 MediCareAI-Agent

> **Multi-Agent Autonomous Medical Collaboration System**
>
> Patient-driven + AI-assisted + Doctor-validated healthcare platform, reimagined for the Agent era.

---

## 🎯 Vision

MediCareAI-Agent is not a chatbot. It is a **team of specialized medical agents** that:

- **Diagnose** — Analyze symptoms with multi-path RAG and external knowledge
- **Plan** — Create personalized follow-up and treatment schedules
- **Monitor** — Proactively track patient recovery and alert on anomalies
- **Collaborate** — Route complex cases to the right doctor with full context

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) |
| Task Queue | Celery + Redis |
| Database | PostgreSQL 17 + pgvector |
| AI/LLM | OpenAI-compatible (kimi-k2.6 / GLM / DeepSeek / Qwen) |
| Auth | JWT + Role-based (Patient / Doctor / Admin / Guest) |
| Frontend | React 19 + TypeScript 6 + Vite 8 + MUI 9 |
| Deploy | Docker Compose → VPS (production) |

## 🚀 Quick Start

### 1. Clone & Configure

```bash
git clone https://github.com/houge-langley/MediCareAI-Agent.git
cd MediCareAI-Agent
cp .env.example .env
# Edit .env with your real API keys and secrets
```

### 2. Local Development (Docker)

```bash
docker compose up -d
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### 3. Run Tests

```bash
cd backend
pip install -e ".[dev]"
pytest -q
```

## 📋 Development Workflow

```
💻 Local Dev          📡 Push               🔧 VPS Production
┌──────────────┐    ┌──────────┐    ┌──────────────┐
│ Edit code      │──────────▶│ git push │──────────▶│ git pull   │
│ Write tests    │    │  origin  │    │ docker     │
│ Run locally    │    │  main     │    │ compose up │
└──────────────┘    └──────────┘    └──────────────┘
       ▲                                          │
       │         ❌ Build fails / bug               │
       └──────────────────────────────────────────┘
```

## 📝 Documentation

Full docs in [`docs/`](./docs/):

| Document | Content |
|----------|---------|
| [`README.mdx`](./docs/README.mdx) | Index & Quick Start |
| [`architecture.mdx`](./docs/architecture.mdx) | System Architecture (current state) |
| [`backend.mdx`](./docs/backend.mdx) | API Endpoints, Services, Models |
| [`frontend.mdx`](./docs/frontend.mdx) | Component Tree, State Machine |
| [`database.mdx`](./docs/database.mdx) | Schema, Migrations |
| [`deployment.mdx`](./docs/deployment.mdx) | Deploy Workflow, Debugging |
| [`todos.mdx`](./docs/todos.mdx) | Known Issues & Roadmap (P0-P3) |

The original architecture proposal is at [`PROPOSAL.md`](./PROPOSAL.md) (v1.0.0, historical).

## 📁 Project Structure

```
MediCareAI-Agent/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST + SSE endpoints
│   │   ├── services/         # Agent logic (DiagnosisAgent, LLM)
│   │   ├── models/           # SQLAlchemy models
│   │   └── db/               # Session + Migrations
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/       # ChatPage, UploadReportCard, etc.
│   │   ├── api/              # API client + SSE handlers
│   │   ├── theme/            # Design tokens
│   │   └── types/            # TypeScript types
│   └── package.json
├── docs/                     # Project documentation (.mdx)
├── nginx/                    # Reverse proxy config
├── searxng/                  # Search engine config
├── docker-compose.yml        # Production stack
├── docker-compose.prod.yml
└── Dockerfile
```

## 🎯 Current Status

| Feature | Status |
|---------|:--:|
| Three-track diagnosis (Track1+2+3) | ✅ |
| Post-diagnosis chat (Plan B+C) | ✅ |
| Lab report bridge (normalized) | ✅ |
| Upload UX (Banner + UploadReportCard) | ✅ |
| MedicalCase (Plan C layered model) | ✅ |
| Doctor Dashboard | [TODO] |
| DoctorAgent / KnowledgeAgent | [TODO] |
| MCP / GraphRAG / Android App | [TODO] |

## 📝 License

[MIT](LICENSE) © 2026 Houge Langley
