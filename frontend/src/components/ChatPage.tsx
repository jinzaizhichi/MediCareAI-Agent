import { useState, useRef, useEffect, useCallback, useLayoutEffect } from 'react';
import {
  Box,
  CssBaseline,
  AppBar,
  Toolbar,
  IconButton,
  Typography,
  Fab,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import type { ChatMessageItem, ChatSession, GuestStatus, SSEEvent, DiagnosisReport, WorkflowStep, LabReportResult } from '../types/agent';
import { agentApi } from '../api/agent';
import { uploadDocument, getParseResult } from '../api/documents';
import { getToken } from '../api/client';
import Sidebar from './Sidebar';
import ChatMessage from './ChatMessage';
import ChatInput from './ChatInput';
import GuestBanner from './GuestBanner';
import PendingCardsPanel from './PendingCardsPanel';
import FullScreenReport from './FullScreenReport';
import UploadStatusBanner from './UploadStatusBanner';

interface UploadItem {
  fileId: string;
  fileName: string;
  status: 'parsing' | 'completed' | 'failed';
}


const QUICK_REPLIES = [
  '头疼还发烧',
  '腹痛拉肚子',
  '咳嗽一周了',
  '近期体检报告解读',
];

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export default function ChatPage() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>();
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [guestStatus, setGuestStatus] = useState<GuestStatus | null>(null);
  const [showScrollDown, setShowScrollDown] = useState(false);
  const [answeredIds, setAnsweredIds] = useState<Set<string>>(new Set());
  const [reportData, setReportData] = useState<DiagnosisReport | null>(null);
  const [showReport, setShowReport] = useState(false);
  const [isDiagnosed, setIsDiagnosed] = useState(false);
  type ChatMode = 'idle' | 'consulting' | 'diagnosed';
  const [chatMode, setChatMode] = useState<ChatMode>('idle');
  const backendSessionIdRef = useRef<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const didInit = useRef(false);
  const pendingSessionRef = useRef<{ sessionId: string; questionId: string } | null>(null);
  const [activeUploads, setActiveUploads] = useState<UploadItem[]>([]);
  const uploadBannerDismissed = useRef(false);
  const failedFileAttempts = useRef<Map<string, number>>(new Map());

  // 初始化：检查认证状态，未登录时自动创建访客 session
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;

    const initAuth = async () => {
      if (getToken()) return;
      const stored = agentApi.getGuestStatus();
      if (stored) {
        try {
          const status = await agentApi.fetchGuestStatus();
          if (status) {
            setGuestStatus(status);
            return;
          }
        } catch {
          // Token invalid — will create new one below
        }
      }
      // Clear any stale token before creating new session
      agentApi.clearGuestToken();
      try {
        await agentApi.createGuestSession();
        setGuestStatus(agentApi.getGuestStatus());
      } catch (e) {
        console.error('Failed to create guest session:', e);
      }
    };

    initAuth();
  }, []);

  // 滚动到底部 — 仅在新消息增加且用户接近底部时滚动
  const prevMsgLen = useRef(messages.length);
  useEffect(() => {
    const hasActiveQuestions = messages.some(m => m.role === 'agent' && (m.interviewQuestions?.length));
    if (!hasActiveQuestions && messages.length > prevMsgLen.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevMsgLen.current = messages.length;
  }, [messages]);

  // 滚动监听
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    setShowScrollDown(!nearBottom);
  }, []);

  // 创建新对话
  const startNewSession = useCallback(() => {
    const id = generateId();
    const newSession: ChatSession = {
      id,
      title: '新对话',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      message_count: 0,
    };
    setSessions((prev) => [newSession, ...prev]);
    setCurrentSessionId(id);
    setChatMode('idle');
    setIsDiagnosed(false);
    setReportData(null);
    setShowReport(false);
    backendSessionIdRef.current = null;
    pendingSessionRef.current = null;
    setAnsweredIds(new Set());
    setActiveUploads([]);
    uploadBannerDismissed.current = false;
    failedFileAttempts.current = new Map();
    setMessages([
      {
        id: generateId(),
        role: 'agent',
        content: `您好！我是 MediCareAI 智能医疗助手🩺\n\n我可以帮您：\n• 分析症状并给出初步诊断\n• 解读检查报告\n• 提供健康建议\n\n请描述您的不适感受，或上传相关检查报告。`,
        timestamp: new Date(),
      },
    ]);
  }, []);

  // 初始化：使用 useLayoutEffect + setTimeout 将 setState 延迟到下一个 tick
  useLayoutEffect(() => {
    if (sessions.length > 0) return;
    const timer = setTimeout(() => {
      startNewSession();
    }, 0);
    return () => clearTimeout(timer);
  }, [sessions.length, startNewSession]);

  const handleSend = useCallback(
    async (text: string) => {
      if (isStreaming || !currentSessionId) return;

      if (chatMode === 'idle') {
        setChatMode('consulting');
        console.log('[DEBUG-CARD] chatMode → consulting');
      }

      if (!getToken()) {
        localStorage.removeItem('guest_token');
        localStorage.removeItem('guest_status');
        try {
          await agentApi.createGuestSession();
        } catch {
          // Continue with whatever token we have — better than blocking send
        }
      }

      const userMsg: ChatMessageItem = {
        id: generateId(),
        role: 'user',
        content: text,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);

      setIsStreaming(true);
      const agentMsgId = generateId();
      let content = '';
      let structured: DiagnosisReport | undefined;
      const workflowSteps: WorkflowStep[] = [];

      // 工作流步骤辅助函数
      const addStep = (step: Omit<WorkflowStep, 'id' | 'timestamp'>) => {
        const newStep: WorkflowStep = { ...step, id: generateId(), timestamp: new Date() };
        workflowSteps.push(newStep);
        setMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === agentMsgId);
          if (idx === -1) {
            return [...prev, { id: agentMsgId, role: 'agent', content: '', timestamp: new Date(), isStreaming: true, workflowSteps: [...workflowSteps] }];
          }
          const next = prev.slice();
          next[idx] = { ...next[idx], workflowSteps: [...workflowSteps] };
          return next;
        });
      };

      // Plan C: diagnosed mode routes to dedicated chat endpoint
      if (chatMode === 'diagnosed' && backendSessionIdRef.current) {
        try {
          await agentApi.streamChat(
            backendSessionIdRef.current,
            text,
            (event: SSEEvent) => {
              switch (event.event) {
                case 'text':
                  content += event.data?.text || '';
                  setMessages((prev) => {
                    const idx = prev.findIndex((m) => m.id === agentMsgId);
                    if (idx === -1) {
                      return [...prev, { id: agentMsgId, role: 'agent', content, timestamp: new Date(), isStreaming: true }];
                    }
                    const next = prev.slice();
                    next[idx] = { ...next[idx], content, isStreaming: true };
                    return next;
                  });
                  break;
                case 'complete':
                  setMessages((prev) => {
                    const idx = prev.findIndex((m) => m.id === agentMsgId);
                    if (idx === -1) return prev;
                    const next = prev.slice();
                    next[idx] = { ...next[idx], isStreaming: false };
                    return next;
                  });
                  setIsStreaming(false);
                  break;
                case 'error':
                  setMessages((prev) => [...prev, { id: generateId(), role: 'agent', content: `请求失败，请重试`, timestamp: new Date() }]);
                  setIsStreaming(false);
                  break;
              }
            }
          );
        } catch {
          setMessages((prev) => [...prev, { id: generateId(), role: 'agent', content: `连接失败，请检查网络后重试`, timestamp: new Date() }]);
          setIsStreaming(false);
        }
        return;
      }

      // Lightweight patient history — only user Q&A, exclude verbose reports.
      // The diagnosis pipeline uses this for classify_intent context.
      // The chat endpoint (_build_chat_context) loads full context from DB.
      const patientHistory = messages
        .filter(m => m.role === 'user' && m.content.length < 500)
        .map(m => `患者: ${m.content.slice(0, 300)}`)
        .join('\n')
        .slice(0, 3000);

      try {
        await agentApi.streamDiagnose(
          { message: text, session_id: currentSessionId, patient_history: patientHistory },
          (event: SSEEvent) => {
            switch (event.event) {
              case 'intent': {
                const intent = event.data?.intent as string || 'diagnosis';
                const confidence = event.data?.confidence as string || 'medium';
                const reasoning = event.data?.reasoning as string || '';
                addStep({
                  type: 'intent',
                  status: 'done',
                  title: `MasterAgent 识别到意图: ${intent}`,
                  detail: `置信度: ${confidence}${reasoning ? ` | ${reasoning}` : ''}`,
                });
                break;
              }
              case 'agent_switch': {
                const agentDisplay = event.data?.agent_display as string || event.data?.agent as string || '未知';
                addStep({
                  type: 'agent_switch',
                  status: 'done',
                  title: `已切换到 ${agentDisplay}`,
                  detail: event.data?.message as string || '',
                });
                break;
              }
              case 'thinking': {
                const stepName = event.data?.step as string || 'thinking';
                const messageText = event.data?.message as string || '正在分析...';
                addStep({
                  type: 'thinking',
                  status: 'done',
                  title: messageText,
                  detail: event.data?.detail as string || '',
                });
                break;
              }
              case 'tool_call': {
                const toolName = event.data?.tool as string || '未知工具';
                addStep({
                  type: 'tool_call',
                  status: 'done',
                  title: event.data?.message as string || `正在调用 ${toolName}...`,
                  toolName,
                  toolParams: (event.data?.params as Record<string, unknown>) || {},
                });
                break;
              }
              case 'tool_result': {
                const toolName = event.data?.tool as string || '未知工具';
                addStep({
                  type: 'tool_result',
                  status: 'done',
                  title: event.data?.message as string || `${toolName} 执行完成`,
                  toolName,
                  toolResult: event.data?.result,
                });
                break;
              }
              case 'text': {
                content += event.data?.text || '';
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, { id: agentMsgId, role: 'agent', content, timestamp: new Date(), isStreaming: true, workflowSteps: [...workflowSteps] }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], content, isStreaming: true, workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              }
              case 'structured':
                structured = event.data as unknown as DiagnosisReport;
                setReportData(structured);
                setShowReport(true);
                setIsDiagnosed(true);
                setChatMode('diagnosed');
                pendingSessionRef.current = null;
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) return prev;
                  const next = prev.slice();
                  next[idx] = { ...next[idx], structured, content: content || next[idx].content || '已生成诊断报告', workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              case 'question': {
                const q = event.data as unknown as { question_id: string; question: string; type: string; options?: string[]; hint?: string; allow_skip?: boolean; colloquial_phase?: string; phase?: string; questions?: InterviewQuestion[] };
                const qs: InterviewQuestion[] = 'questions' in event.data ? (event.data as { questions: InterviewQuestion[] }).questions : [q as InterviewQuestion];
                  console.log("[DEBUG-CARD] handleSend question:", { count: qs.length, ids: qs.map(x => x.question_id), chatMode });
                // sessionId will be set when 'complete' event with status='waiting_for_answer' arrives
                // For now, just set the questionId; sessionId is updated in the 'complete' handler
                if (!pendingSessionRef.current) {
                  pendingSessionRef.current = { sessionId: '', questionId: q.question_id };
                } else {
                  pendingSessionRef.current.questionId = q.question_id;
                }
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, {
                      id: agentMsgId,
                      role: 'agent',
                      content: '',
                      timestamp: new Date(),
                      isStreaming: true,
                      workflowSteps: [...workflowSteps],
                      interviewQuestions: qs,
                    }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], isStreaming: true, workflowSteps: [...workflowSteps], interviewQuestions: qs };
                  return next;
                });
                break;
              }
              case 'interview_progress': {
                addStep({
                  type: 'thinking',
                  status: 'done',
                  title: '📋 已收集问诊信息',
                  detail: Object.entries(event.data?.collected as Record<string, unknown> || {})
                    .filter(([k]) => !k.startsWith('__'))
                    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', '),
                });
                break;
              }
              case 'error': {
                const errorMsg = event.data?.message as string || event.data?.error as string || '服务异常';
                addStep({
                  type: 'thinking',
                  status: 'error',
                  title: `错误: ${errorMsg}`,
                });
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, { id: agentMsgId, role: 'agent', content: `❌ 错误: ${errorMsg}`, timestamp: new Date(), workflowSteps: [...workflowSteps] }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], content: `❌ 错误: ${errorMsg}`, isStreaming: false, workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              }
              case 'complete': {
                const sid = event.data?.session_id as string;
                if (sid) backendSessionIdRef.current = sid;
                const status = event.data?.status as string;
                if (status === 'waiting_for_answer') {
                  console.log("[DEBUG-CARD] complete waiting_for_answer:", { sid, hasPending: !!pendingSessionRef.current });
                  if (sid) {
                    if (!pendingSessionRef.current) {
                      pendingSessionRef.current = { sessionId: sid, questionId: '' };
                    } else {
                      pendingSessionRef.current.sessionId = sid;
                    }
                  }
                  break;
                }
                addStep({
                  type: 'complete',
                  status: 'done',
                  title: event.data?.message as string || '✅ 响应完成',
                });
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) return prev;
                  const next = prev.slice();
                  next[idx] = { ...next[idx], isStreaming: false, workflowSteps: [...workflowSteps] };
                  return next;
                });
                setIsStreaming(false);
                pendingSessionRef.current = null;
                break;
              }
            }
          }
        );
      } catch {
        setMessages((prev) => [...prev, { id: generateId(), role: 'agent', content: `❌ 连接失败，请检查网络后重试`, timestamp: new Date() }]);
        setIsStreaming(false);
      }
    },
    [isStreaming, currentSessionId, chatMode]
  );

  const handleInterviewAnswer = useCallback(
    async (questionId: string, answer: string) => {
      // P0-1: Block interview answers after diagnosis
      if (chatMode === 'diagnosed') return;

      const pending = pendingSessionRef.current;
      if (!pending?.sessionId) return;

      setAnsweredIds((prev) => new Set([...prev, questionId]));

      // Disable the previous agent message's interview question
      setMessages((prev) => {
        const idx = prev.findLastIndex((m) => m.role === 'agent' && (m.interviewQuestion?.question_id === questionId || m.interviewQuestions?.some(iq => iq.question_id === questionId)));
        if (idx === -1) return prev;
        const next = prev.slice();
        const remaining = (next[idx].interviewQuestions || []).filter(iq => iq.question_id !== questionId);
        next[idx] = { ...next[idx], interviewQuestion: undefined, interviewQuestions: remaining.length > 0 ? remaining : undefined };
        if (remaining.length === 0) next[idx].isStreaming = false;
        return next;
      });

      // Add user answer as a new message
      const userAnswerMsg: ChatMessageItem = {
        id: generateId(),
        role: 'user',
        content: answer,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userAnswerMsg]);

      setIsStreaming(true);
      const agentMsgId = generateId();
      let content = '';
      let structured: DiagnosisReport | undefined;
      const workflowSteps: WorkflowStep[] = [];

      const addStep = (step: Omit<WorkflowStep, 'id' | 'timestamp'>) => {
        const newStep: WorkflowStep = { ...step, id: generateId(), timestamp: new Date() };
        workflowSteps.push(newStep);
        setMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === agentMsgId);
          if (idx === -1) {
            return [...prev, { id: agentMsgId, role: 'agent', content: '', timestamp: new Date(), isStreaming: true, workflowSteps: [...workflowSteps] }];
          }
          const next = prev.slice();
          next[idx] = { ...next[idx], workflowSteps: [...workflowSteps] };
          return next;
        });
      };

      try {
        await agentApi.streamDiagnoseContinue(
          { session_id: pending.sessionId, question_id: questionId, answer },
          (event: SSEEvent) => {
            switch (event.event) {
              case 'thinking': {
                addStep({
                  type: 'thinking',
                  status: 'done',
                  title: (event.data?.message as string) || '正在分析...',
                  detail: (event.data?.detail as string) || '',
                });
                break;
              }
              case 'tool_call': {
                const toolName = (event.data?.tool as string) || '未知工具';
                addStep({
                  type: 'tool_call',
                  status: 'done',
                  title: (event.data?.message as string) || `正在调用 ${toolName}...`,
                  toolName,
                  toolParams: (event.data?.params as Record<string, unknown>) || {},
                });
                break;
              }
              case 'tool_result': {
                const toolName = (event.data?.tool as string) || '未知工具';
                addStep({
                  type: 'tool_result',
                  status: 'done',
                  title: (event.data?.message as string) || `${toolName} 执行完成`,
                  toolName,
                  toolResult: event.data?.result,
                });
                break;
              }
              case 'text': {
                content += (event.data?.text as string) || '';
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, { id: agentMsgId, role: 'agent', content, timestamp: new Date(), isStreaming: true, workflowSteps: [...workflowSteps] }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], content, isStreaming: true, workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              }
              case 'structured':
                structured = event.data as unknown as DiagnosisReport;
                setReportData(structured);
                setShowReport(true);
                setIsDiagnosed(true);
                setChatMode('diagnosed');
                pendingSessionRef.current = null;
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) return prev;
                  const next = prev.slice();
                  next[idx] = { ...next[idx], structured, content: content || next[idx].content || '已生成诊断报告', workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              case 'question': {
                const q = event.data as unknown as { question_id: string; question: string; type: string; options?: string[]; hint?: string; allow_skip?: boolean; colloquial_phase?: string; phase?: string; questions?: InterviewQuestion[] };
                const qs: InterviewQuestion[] = 'questions' in event.data ? (event.data as { questions: InterviewQuestion[] }).questions : [q as InterviewQuestion];
                  console.log("[DEBUG-CARD] handleInterviewAnswer question:", { count: qs.length, ids: qs.map(x => x.question_id) });
                // sessionId will be set when 'complete' event with status='waiting_for_answer' arrives
                // For now, just set the questionId; sessionId is updated in the 'complete' handler
                if (!pendingSessionRef.current) {
                  pendingSessionRef.current = { sessionId: '', questionId: q.question_id };
                } else {
                  pendingSessionRef.current.questionId = q.question_id;
                }
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, {
                      id: agentMsgId,
                      role: 'agent',
                      content: '',
                      timestamp: new Date(),
                      isStreaming: true,
                      workflowSteps: [...workflowSteps],
                      interviewQuestions: qs,
                    }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], isStreaming: true, workflowSteps: [...workflowSteps], interviewQuestions: qs };
                  return next;
                });
                break;
              }
              case 'interview_progress': {
                addStep({
                  type: 'thinking',
                  status: 'done',
                  title: '📋 已收集问诊信息',
                  detail: Object.entries(event.data?.collected as Record<string, unknown> || {})
                    .filter(([k]) => !k.startsWith('__'))
                    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', '),
                });
                break;
              }
              case 'error': {
                const errorMsg = (event.data?.message as string) || (event.data?.error as string) || '服务异常';
                addStep({
                  type: 'thinking',
                  status: 'error',
                  title: `错误: ${errorMsg}`,
                });
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, { id: agentMsgId, role: 'agent', content: `❌ 错误: ${errorMsg}`, timestamp: new Date(), workflowSteps: [...workflowSteps] }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], content: `❌ 错误: ${errorMsg}`, isStreaming: false, workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              }
              case 'complete': {
                const status = event.data?.status as string;
                if (status === 'waiting_for_answer') {
                  console.log("[DEBUG-CARD] complete waiting_for_answer:", { sid, hasPending: !!pendingSessionRef.current });
                  const sid = event.data?.session_id as string;
                  if (sid) {
                    if (!pendingSessionRef.current) {
                      pendingSessionRef.current = { sessionId: sid, questionId: '' };
                    } else {
                      pendingSessionRef.current.sessionId = sid;
                      // Keep the existing questionId, don't overwrite it
                    }
                  }
                  break;
                }
                if (status === 'already_diagnosed') {
                  setIsDiagnosed(true);
                  setChatMode('diagnosed');
                  setMessages((prev) => {
                    const idx = prev.findIndex((m) => m.id === agentMsgId);
                    if (idx === -1) {
                      return [...prev, { id: agentMsgId, role: 'system', content: '✅ 问诊已完成，诊断报告已生成。', timestamp: new Date() }];
                    }
                    const next = prev.slice();
                    next[idx] = { ...next[idx], isStreaming: false, content: '✅ 问诊已完成，诊断报告已生成。', workflowSteps: [...workflowSteps] };
                    return next;
                  });
                  setIsStreaming(false);
                  pendingSessionRef.current = null;
                  break;
                }
                addStep({
                  type: 'complete',
                  status: 'done',
                  title: (event.data?.message as string) || '✅ 响应完成',
                });
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) return prev;
                  const next = prev.slice();
                  next[idx] = { ...next[idx], isStreaming: false, workflowSteps: [...workflowSteps] };
                  return next;
                });
                setIsStreaming(false);
                pendingSessionRef.current = null;
                break;
              }
            }
          }
        );
      } catch {
        setMessages((prev) => [...prev, { id: generateId(), role: 'agent', content: `❌ 连接失败，请检查网络后重试`, timestamp: new Date() }]);
        setIsStreaming(false);
      }
    },
    [isStreaming, currentSessionId]
  );

  const handleQuickReply = useCallback(
    (text: string) => {
      if (isStreaming) return;
      handleSend(text);
    },
    [isStreaming, handleSend]
  );

  const handleFileUpload = useCallback(
    async (file: File) => {
      const uploadId = generateId();

      setActiveUploads((prev) => [
        ...prev,
        { fileId: uploadId, fileName: file.name, status: 'parsing' },
      ]);

      setMessages((prev) => [
        ...prev,
        {
          id: uploadId,
          role: 'agent',
          content: '',
          timestamp: new Date(),
          uploadStatus: 'processing',
          uploadFileName: file.name,
        },
      ]);

      try {
        const uploadRes = await uploadDocument(file);
        const fileId = uploadRes.file_id;

        // Poll for result
        const poll = setInterval(async () => {
          try {
            const result = await getParseResult(fileId);

            if (result.status === 'completed' && result.result) {
              clearInterval(poll);
              setActiveUploads((prev) =>
                prev.map((u) => (u.fileId === uploadId ? { ...u, status: 'completed' } : u))
              );
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === uploadId
                    ? {
                        ...m,
                        uploadStatus: 'completed',
                        labReport: result.result,
                        content: `📄 ${file.name} 解析完成`,
                      }
                    : m
                )
              );
              // Immediately post completed lab report to the session
              try {
                const token = getToken();
                const uploadSessionId = backendSessionIdRef.current || currentSessionId;
                await fetch(`/api/v1/agents/sessions/${uploadSessionId}/lab-reports`, {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { Authorization: `Bearer ${token}` } : { 'X-Guest-Token': localStorage.getItem('guest_token') || '' }),
                  },
                  body: JSON.stringify([result.result]),
                });
              } catch {
                console.warn('[DEBUG] Failed to post lab report for:', file.name);
              }
            } else if (result.status === 'failed') {
              clearInterval(poll);
              const prevFails = failedFileAttempts.current.get(file.name) || 0;
              failedFileAttempts.current.set(file.name, prevFails + 1);
              setActiveUploads((prev) =>
                prev.map((u) => (u.fileId === uploadId ? { ...u, status: 'failed' } : u))
              );
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === uploadId
                    ? {
                        ...m,
                        uploadStatus: 'failed',
                        uploadError: result.error || '解析失败',
                        content: `❌ ${file.name} 解析失败`,
                      }
                    : m
                )
              );
            }
          } catch {
            // Keep polling on transient errors
          }
        }, 1500);

        // Timeout after 120 seconds
        setTimeout(() => {
          clearInterval(poll);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === uploadId && m.uploadStatus === 'processing'
                ? { ...m, uploadStatus: 'failed', uploadError: '解析超时，请重试', content: `❌ ${file.name} 解析超时` }
                : m
            )
          );
        }, 120000);
      } catch (err: any) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === uploadId
              ? {
                  ...m,
                  uploadStatus: 'failed',
                  uploadError: err.message || '上传失败',
                  content: `❌ ${file.name} 上传失败`,
                }
              : m
          )
        );
      }
    },
    [currentSessionId, chatMode]
  );

  const handleNewChat = useCallback(() => {
    startNewSession();
  }, [startNewSession]);

  return (
    <Box sx={{ display: 'flex', height: '100vh', bgcolor: '#FAF7F2' }}>
      <CssBaseline />
      <Sidebar
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={setCurrentSessionId}
        onNewChat={handleNewChat}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <AppBar position="static" elevation={0} sx={{ bgcolor: 'background.paper', borderBottom: '1px solid #F5E6D3' }}>
          <Toolbar sx={{ minHeight: 56 }}>
            <IconButton edge="start" onClick={() => setMobileOpen(true)} sx={{ mr: 1, display: { sm: 'none' } }}>
              <MenuIcon />
            </IconButton>
            <Typography variant="h6" sx={{ flex: 1, fontWeight: 700, color: '#5C4033' }}>
              MediCareAI
            </Typography>
            {guestStatus && (
              <GuestBanner
                status={guestStatus}
              onRegister={() => { window.location.href = '/register'; }}
              onLogin={() => { window.location.href = '/login'; }}
              />
            )}
          </Toolbar>
        </AppBar>

        <Box
          ref={scrollRef}
          onScroll={handleScroll}
          sx={{ flex: 1, overflowY: 'auto', p: { xs: 1, sm: 2 }, display: 'flex', flexDirection: 'column', gap: 0.5 }}
        >
          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              message={msg}
              onInterviewAnswer={handleInterviewAnswer}
            />
          ))}
          <div ref={messagesEndRef} />
        </Box>

        {chatMode === 'consulting' && (
          <PendingCardsPanel
            messages={messages}
            answeredIds={answeredIds}
            onAnswer={handleInterviewAnswer}
          />
        )}

        {showScrollDown && (
          <Fab
            size="small"
            onClick={() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })}
            sx={{ position: 'absolute', bottom: 100, right: 24, bgcolor: 'background.paper', boxShadow: 2 }}
          >
            <KeyboardArrowDownIcon />
          </Fab>
        )}

        {reportData && (
          <Fab
            size="small"
            onClick={() => setShowReport(true)}
            sx={{ position: 'absolute', bottom: 100, right: 24, bgcolor: 'primary.main', color: '#fff', boxShadow: 3, zIndex: 1200 }}
          >
            📊
          </Fab>
        )}

        <Box sx={{ p: 2, borderTop: '1px solid #F5E6D3', bgcolor: 'background.paper' }}>
          {(activeUploads.length > 0 || (chatMode === 'diagnosed' && !uploadBannerDismissed.current)) && (
            <UploadStatusBanner
              uploads={activeUploads}
              failedAttempts={failedFileAttempts.current}
              mode={chatMode === 'diagnosed' ? 'diagnosed' : 'consulting'}
              onDismiss={() => {
                setActiveUploads([]);
                uploadBannerDismissed.current = true;
              }}
            />
          )}
          {chatMode === 'consulting' ? (
            <Typography variant="body2" color="text.secondary" align="center" sx={{ py: 1 }}>
              📋 正在问诊中，请通过下方问诊卡选择最佳答案
            </Typography>
          ) : (
            <ChatInput
              onSend={handleSend}
              disabled={isStreaming}
              quickReplies={chatMode === 'idle' && messages.length <= 2 ? QUICK_REPLIES : undefined}
              onQuickReply={handleQuickReply}
              onFileUpload={handleFileUpload}
              placeholder={
                activeUploads.some((u) => u.status === 'parsing')
                  ? '报告解读完成后提问效果更好哦～'
                  : undefined
              }
            />
          )}
        </Box>
      </Box>

      <FullScreenReport
        report={reportData!}
        visible={!!reportData && showReport}
        onClose={() => setShowReport(false)}
      />
    </Box>
  );
}
