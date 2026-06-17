import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Container,
  Box,
  Typography,
  Card,
  CardContent,
  Tabs,
  Tab,
  Checkbox,
  Chip,
  IconButton,
  Divider,
  Stack,
  LinearProgress,
} from '@mui/material';
import ArrowBackIosNewIcon from '@mui/icons-material/ArrowBackIosNew';
import CalendarTodayIcon from '@mui/icons-material/CalendarToday';
import FlagIcon from '@mui/icons-material/Flag';
import AssignmentTurnedInIcon from '@mui/icons-material/AssignmentTurnedIn';
import { listCarePlans, ackTask } from '../../api/patient';
import type { CarePlan } from '../../api/patient';
import { flexRowGap05Mb05, pageHeader } from '../../styles/sxUtils';


const warmText = '#5C4033';
const warmPrimary = '#E8956A';
const warmBg = '#FFFBF5';

/* ---------- 工具函数 ---------- */
function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function isExpired(plan: CarePlan): boolean {
  if (!plan.end_date) return false;
  return plan.end_date < todayStr();
}

function isAllCompleted(plan: CarePlan): boolean {
  return plan.tasks.length > 0 && plan.tasks.every((t) => t.completed);
}

function getPlanStatus(plan: CarePlan): '进行中' | '已完成' | '已过期' {
  if (isAllCompleted(plan)) return '已完成';
  if (isExpired(plan)) return '已过期';
  return '进行中';
}

function completionRate(plan: CarePlan): number {
  if (!plan.tasks.length) return 0;
  return Math.round((plan.tasks.filter((t) => t.completed).length / plan.tasks.length) * 100);
}

/* ---------- 组件 ---------- */
export default function FollowUpPage() {
  const navigate = useNavigate();
  const [plans, setPlans] = useState<CarePlan[]>(fallbackPlans);
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    listCarePlans()
      .then((data) => {
        if (mounted) {
          const merged = data.length ? data : fallbackPlans;
          setPlans(merged);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) {
          setPlans(fallbackPlans);
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleToggleTask = async (planId: string, taskId: string) => {
    setPlans((prev) =>
      prev.map((plan) => {
        if (plan.id !== planId) return plan;
        const updatedTasks = plan.tasks.map((t) =>
          t.id === taskId ? { ...t, completed: !t.completed } : t
        );
        return { ...plan, tasks: updatedTasks };
      })
    );

    try {
      await ackTask(planId, taskId);
    } catch {
      // 如果 API 失败，已在本地切换状态，保持演示体验
    }
  };

  const { active, pending, history } = useMemo(() => {
    const t = todayStr();
    const activeList: CarePlan[] = [];
    const pendingList: CarePlan[] = [];
    const historyList: CarePlan[] = [];

    plans.forEach((plan) => {
      const expired = isExpired(plan);
      const allDone = isAllCompleted(plan);
      const inRange = plan.start_date <= t && (!plan.end_date || plan.end_date >= t);

      if (allDone || expired) {
        historyList.push(plan);
      } else if (inRange && plan.tasks.some((t) => t.completed)) {
        activeList.push(plan);
      } else {
        pendingList.push(plan);
      }
    });

    return { active: activeList, pending: pendingList, history: historyList };
  }, [plans]);

  const tabs = [
    { label: `进行中 (${active.length})`, list: active },
    { label: `待完成 (${pending.length})`, list: pending },
    { label: `历史记录 (${history.length})`, list: history },
  ];

  const statusColor: Record<string, string> = {
    进行中: '#E8956A',
    已完成: '#66BB6A',
    已过期: '#B0B0B0',
  };

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: warmBg, pb: 6 }}>
      <Container maxWidth="md">
        <Box sx={pageHeader}>
          <IconButton onClick={() => navigate('/chat')} sx={{ color: warmText }}>
            <ArrowBackIosNewIcon />
          </IconButton>
          <Typography variant="h5" sx={{ fontWeight: 700, color: warmText, flex: 1 }}>
            📅 随访计划
          </Typography>
        </Box>

        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}
          TabIndicatorProps={{ sx: { bgcolor: warmPrimary } }}>
          <Tab label="进行中" value="active" />
          <Tab label="已完成" value="completed" />
          <Tab label="全部" value="all" />
        </Tabs>

        {loading && <Typography sx={{ textAlign: 'center', py: 4 }}>加载中...</Typography>}

        {!loading && filtered.length === 0 && (
          <Typography sx={{ textAlign: 'center', py: 4, color: '#8B7355' }}>
            暂无{tab === 'active' ? '进行中的' : tab === 'completed' ? '已完成的' : ''}随访计划
          </Typography>
        )}

        <Stack spacing={2}>
          {filtered.map((plan) => {
            const tasks = (plan as any).tasks || {};
            const taskEntries = tasks.tasks || Object.entries(tasks);
            const done = Array.isArray(taskEntries)
              ? taskEntries.filter((t: any) => t.status === 'completed' || t.completed).length
              : 0;
            const total = Array.isArray(taskEntries) ? taskEntries.length : 0;
            const pct = total > 0 ? Math.round((done / total) * 100) : 0;

            return (
              <Card key={plan.id} sx={{ borderRadius: 3 }}>
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                    <Typography variant="h6" sx={{ color: warmText, fontWeight: 600 }}>
                      {plan.title || '护理计划'}
                    </Typography>
                    <Chip label={plan.status === 'completed' ? '已完成' : '进行中'}
                      color={plan.status === 'completed' ? 'success' : 'warning'} size="small" />
                  </Box>
                  {plan.description && (
                    <Typography variant="body2" sx={{ color: '#8B7355', mb: 1 }}>{plan.description}</Typography>
                  )}
                  <LinearProgress variant="determinate" value={pct}
                    sx={{ mb: 1, height: 8, borderRadius: 4, bgcolor: '#F5E6D3',
                      '& .MuiLinearProgress-bar': { bgcolor: warmPrimary } }} />
                  <Typography variant="caption" color="text.secondary">进度 {pct}%</Typography>
                  <Divider sx={{ my: 1.5 }} />
                  <Stack spacing={1}>
                    {Array.isArray(taskEntries) && taskEntries.map((task: any, idx: number) => (
                      <Box key={task.id || idx} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Checkbox checked={task.status === 'completed' || task.completed}
                          onChange={() => handleAck(plan.id, task.id || String(idx))}
                          disabled={task.status === 'completed' || task.completed}
                          size="small" sx={{ color: warmPrimary, '&.Mui-checked': { color: warmPrimary } }} />
                        <Typography variant="body2" sx={{
                          flex: 1, color: warmText,
                          textDecoration: (task.status === 'completed' || task.completed) ? 'line-through' : 'none',
                        }}>
                          {task.description || task.name || `任务 ${idx + 1}`}
                        </Typography>
                      </Box>
                    ))}
                  </Stack>
                  {plan.start_date && (
                    <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                      开始: {new Date(plan.start_date).toLocaleDateString('zh-CN')}
                      {plan.end_date && ` — 结束: ${new Date(plan.end_date).toLocaleDateString('zh-CN')}`}
                    </Typography>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </Stack>
      </Container>
    </Box>
  );
}
