# 🖥️ MediCareAI-Agent 前端

> React 19 + TypeScript + Vite + MUI v9

完整文档：[`../docs/frontend.mdx`](../docs/frontend.mdx)

---

## 快速开始

```bash
cd frontend
npm install
npm run dev      # Vite 开发服务器
npm run build    # 生产构建
npm run lint     # ESLint
```

---

## 技术栈版本

| 包 | 版本 |
|----|------|
| React | 19 |
| TypeScript | 6 |
| Vite | 8 |
| MUI | 9 |
| react-markdown | 10 |
| react-router-dom | 7 |

---

## 核心组件

| 组件 | 说明 |
|------|------|
| `ChatPage` | 主页面，三模式状态机（idle / consulting / diagnosed） |
| `UploadReportCard` | 统一上传卡片（parsing / completed / failed） |
| `UploadStatusBanner` | 跨模式上传进度横幅（5 种视觉状态） |
| `ChatMessage` | Agent/用户消息渲染，支持 Markdown、诊断卡、化验单 |
| `ChatInput` | 输入区，含文件上传按钮和动态 placeholder |
| `LabReportCard` | 化验单详情展示，含指标表格 |
| `DiagnosisCard` | 结构化诊断报告卡片 |
| `PendingCardsPanel` | consulting 模式问诊卡片面板 |
| `AgentWorkflow` | 多步骤工作流可视化 |

---

## 架构

完整系统架构见 [`../docs/architecture.mdx`](../docs/architecture.mdx)。
