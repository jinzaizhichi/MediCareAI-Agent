# 🖥️ MediCareAI-Agent Frontend

> React 19 + TypeScript + Vite + MUI v9

Full documentation: [`../docs/frontend.mdx`](../docs/frontend.mdx)

## Quick Start

```bash
cd frontend
npm install
npm run dev      # Vite dev server
npm run build    # Production build
npm run lint     # ESLint
```

## Tech Stack

| Package | Version |
|---------|---------|
| React | 19 |
| TypeScript | 6 |
| Vite | 8 |
| MUI | 9 |
| react-markdown | 10 |
| react-router-dom | 7 |

## Key Components

- `ChatPage` — Main page with three-mode state machine (idle/consulting/diagnosed)
- `UploadReportCard` — Unified upload card (parsing/completed/failed)
- `UploadStatusBanner` — Cross-mode upload progress banner (5 visual states)
- `ChatMessage` — Renders agent/user messages with Markdown, diagnosis cards, lab reports
- `ChatInput` — Input area with file upload buttons and dynamic placeholder
- `LabReportCard` — Lab report detail display with indicator table
- `DiagnosisCard` — Structured diagnosis report card
- `PendingCardsPanel` — Interview question cards during consulting mode
- `AgentWorkflow` — Multi-step workflow visualization

## Architecture

See [`../docs/architecture.mdx`](../docs/architecture.mdx) for the full system architecture.

```
