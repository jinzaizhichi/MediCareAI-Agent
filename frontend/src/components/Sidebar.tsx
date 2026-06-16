import { useState } from 'react';
import {
  Box, Drawer, List, ListItem, ListItemButton, ListItemText,
  Typography, IconButton, Divider, Button, Collapse,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ChatIcon from '@mui/icons-material/Chat';
import LogoutIcon from '@mui/icons-material/Logout';
import PersonAddIcon from '@mui/icons-material/PersonAdd';
import type { ChatSession } from '../types/agent';
import { logout } from '../api/auth';
import { useNavigate } from 'react-router-dom';

interface Props {
  sessions: ChatSession[];
  currentSessionId?: string;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
  drawerWidth?: number;
  isGuest: boolean;
}

const DRAWER_WIDTH = 260;

function groupSessionsByDate(sessions: ChatSession[]): Record<string, ChatSession[]> {
  const groups: Record<string, ChatSession[]> = {};
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 86400000).toDateString();

  for (const s of sessions) {
    const d = new Date(s.updated_at);
    const dateStr = d.toDateString();
    let label = d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
    if (dateStr === today) label = '今天';
    else if (dateStr === yesterday) label = '昨天';

    if (!groups[label]) groups[label] = [];
    groups[label].push(s);
  }
  return groups;
}

export default function Sidebar({
  sessions, currentSessionId, onSelectSession, onNewSession,
  mobileOpen, onMobileClose, drawerWidth = DRAWER_WIDTH, isGuest,
}: Props) {
  const [historyOpen, setHistoryOpen] = useState(true);
  const grouped = groupSessionsByDate(sessions);
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  const drawerContent = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ p: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="h6" sx={{ fontWeight: 600, color: 'text.primary' }}>🩺 MediCareAI</Typography>
        <IconButton size="small" onClick={onNewSession} sx={{ color: 'primary.main' }}>
          <AddIcon />
        </IconButton>
      </Box>

      <Divider sx={{ borderColor: '#F5E6D3' }} />

      <Box sx={{ p: 1.5 }}>
        <Button fullWidth variant="contained" startIcon={<AddIcon />} onClick={onNewSession}
          sx={{ borderRadius: 2, textTransform: 'none', bgcolor: 'primary.main', '&:hover': { bgcolor: 'primary.dark' } }}>
          新建会话
        </Button>
      </Box>

      <Box sx={{ flex: 1, overflow: 'auto', px: 1 }}>
        <ListItemButton onClick={() => setHistoryOpen(!historyOpen)} sx={{ borderRadius: 2, py: 0.5 }}>
          <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary', flex: 1 }}>
            🗂️ 会话历史
          </Typography>
          {historyOpen ? <ExpandLessIcon sx={{ color: 'text.secondary' }} /> : <ExpandMoreIcon sx={{ color: 'text.secondary' }} />}
        </ListItemButton>

        <Collapse in={historyOpen}>
          <List dense sx={{ py: 0 }}>
            {Object.entries(grouped).map(([label, items]) => (
              <Box key={label}>
                <Typography variant="caption" color="text.secondary" sx={{ px: 2, py: 0.5, display: 'block', fontSize: 11 }}>
                  {label}
                </Typography>
                {items.map((s) => (
                  <ListItem key={s.id} disablePadding sx={{ mb: 0.5 }}>
                    <ListItemButton selected={s.id === currentSessionId} onClick={() => onSelectSession(s.id)}
                      sx={{
                        borderRadius: 2, py: 0.75,
                        '&.Mui-selected': { bgcolor: '#F5E6D3', '&:hover': { bgcolor: '#F5E6D3' } },
                        '&:hover': { bgcolor: '#FFF8F0' },
                      }}>
                      <ChatIcon sx={{ fontSize: 16, color: 'text.secondary', mr: 1 }} />
                      <ListItemText primary={s.title || '新对话'}
                        slotProps={{ primary: { variant: 'body2', noWrap: true, sx: { color: s.id === currentSessionId ? 'text.primary' : 'text.secondary', fontWeight: s.id === currentSessionId ? 500 : 400 } } }}
                      />
                    </ListItemButton>
                  </ListItem>
                ))}
              </Box>
            ))}
            {sessions.length === 0 && (
              <Typography variant="caption" color="text.secondary" sx={{ px: 2, py: 1, display: 'block' }}>
                暂无会话记录
              </Typography>
            )}
          </List>
        </Collapse>
      </Box>

      <Divider sx={{ borderColor: '#F5E6D3' }} />

      <Box sx={{ p: 1 }}>
        {isGuest ? (
          <Button fullWidth variant="outlined" startIcon={<PersonAddIcon />} onClick={() => navigate('/login')}
            sx={{ borderRadius: 2, textTransform: 'none', color: 'primary.main', borderColor: 'primary.main' }}>
            注册 / 登录
          </Button>
        ) : (
          <Button fullWidth variant="text" startIcon={<LogoutIcon />} onClick={handleLogout}
            sx={{ borderRadius: 2, textTransform: 'none', color: 'text.secondary' }}>
            登出
          </Button>
        )}
      </Box>
    </Box>
  );

  return (
    <>
      <Drawer variant="permanent" sx={{
        width: drawerWidth, flexShrink: 0, display: { xs: 'none', md: 'block' },
        '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box', borderRight: '1px solid #F5E6D3', bgcolor: '#FFFBF5' },
      }} open>
        {drawerContent}
      </Drawer>
      <Drawer variant="temporary" open={mobileOpen} onClose={onMobileClose} ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: 'block', md: 'none' },
          '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box', borderRight: '1px solid #F5E6D3', bgcolor: '#FFFBF5' },
        }}>
        {drawerContent}
      </Drawer>
    </>
  );
}
