# 🏥 MediCareAI-Agent

> 多 Agent 自主医疗协作系统 | Multi-Agent Autonomous Medical Collaboration System
>
> 患者驱动 + AI 辅助 + 医生验证的医疗平台，为 Agent 时代重新构想。

---

## 🎯 愿景

MediCareAI-Agent 不是聊天机器人。它是一支**专业医疗 Agent 团队**，能够：

- **诊断** — 多路径 RAG + 外部知识分析症状
- **规划** — 制定个性化随访和治疗方案
- **监测** — 主动追踪患者康复，异常告警
- **协作** — 将复杂病例以完整上下文路由给合适的医生

---

## 🛠 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) |
| 任务队列 | Celery + Redis |
| 数据库 | PostgreSQL 17 + pgvector |
| AI/LLM | OpenAI 兼容多提供商 (kimi-k2.6 / GLM / DeepSeek / Qwen) |
| 认证 | JWT + 角色制 (患者 / 医生 / 管理员 / 访客) |
| 前端 | React 19 + TypeScript 6 + Vite 8 + MUI 9 |
| 部署 | Docker Compose → VPS（生产环境） |

---

## 🚀 快速开始

### 1. 克隆并配置

```bash
git clone https://github.com/HougeLangley/MediCareAI-Agent.git
cd MediCareAI-Agent
cp .env.example .env
# 编辑 .env 填入真实的 API key 和密钥
```

### 2. 本地开发 (Docker)

```bash
docker compose up -d
# API: http://localhost:8000
# 接口文档: http://localhost:8000/docs
```

### 3. 运行测试

```bash
cd backend
pip install -e ".[dev]"
pytest -q
```

---

## 📋 开发工作流

```
💻 本地开发           📡 推送               🔧 VPS 生产环境
┌──────────────┐    ┌──────────┐    ┌──────────────┐
│ 编辑代码      │───▶│ git push │───▶│ git pull     │
│ 编写测试      │    │  origin  │    │ docker       │
│ 本地运行      │    │  main    │    │ compose up   │
└──────────────┘    └──────────┘    └──────────────┘
       ▲                                      │
       │          ❌ 构建失败 / bug             │
       └──────────────────────────────────────┘
```

---

## 📝 文档

完整文档位于 [`docs/`](./docs/)：

| 文档 | 内容 |
|------|------|
| [`README.mdx`](./docs/README.mdx) | 文档索引与快速开始 |
| [`architecture.mdx`](./docs/architecture.mdx) | 系统架构（当前实现状态） |
| [`backend.mdx`](./docs/backend.mdx) | API 端点、Service 层、模型 |
| [`frontend.mdx`](./docs/frontend.mdx) | 组件树、状态机 |
| [`database.mdx`](./docs/database.mdx) | 数据库 Schema、迁移 |
| [`deployment.mdx`](./docs/deployment.mdx) | 部署流程、调试 |
| [`todos.mdx`](./docs/todos.mdx) | 已知问题与路线图 (P0-P3) |

原始架构提案见 [`PROPOSAL.md`](./PROPOSAL.md)（v1.0.0，历史参考）。

---

## 📁 项目结构

```
MediCareAI-Agent/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST + SSE 端点
│   │   ├── services/         # Agent 逻辑 (DiagnosisAgent, LLM)
│   │   ├── models/           # SQLAlchemy 模型
│   │   └── db/               # 会话管理 + 迁移
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/       # ChatPage, UploadReportCard 等
│   │   ├── api/              # API 客户端 + SSE 处理器
│   │   ├── theme/            # 设计 token
│   │   └── types/            # TypeScript 类型
│   └── package.json
├── docs/                     # 项目文档 (.mdx)
├── nginx/                    # 反向代理配置
├── searxng/                  # 搜索引擎配置
├── docker-compose.yml        # 生产环境编排
├── docker-compose.prod.yml
└── Dockerfile
```

---

## 🎯 当前状态

| 功能 (Feature) | 状态 (Status) |
|------|:--:|
| 三轨问诊 (Track1+2+3) | ✅ |
| 诊断后对话 (方案 B+C) | ✅ |
| 化验单 bridge（归一化） | ✅ |
| 上传 UX（Banner + UploadReportCard） | ✅ |
| MedicalCase（方案 C 分层模型） | ✅ |
| 医生端控制台 | [TODO] |
| DoctorAgent / KnowledgeAgent | [TODO] |
| MCP / GraphRAG / Android App | [TODO] |

---

## 📝 许可证 (License)

[MIT](LICENSE) © 2026 Houge Langley
