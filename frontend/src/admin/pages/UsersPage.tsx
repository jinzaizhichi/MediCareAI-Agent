import { useEffect, useState, useCallback, startTransition } from 'react';
import {
  Box, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider,
  FormControl, FormControlLabel, IconButton, InputLabel, MenuItem, Select, Switch,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField,
  Typography, Alert, Paper, CircularProgress, Tooltip, Grid,
} from '@mui/material';
import EditIcon from '@mui/icons-material/Edit';
import SearchIcon from '@mui/icons-material/Search';
import CancelIcon from '@mui/icons-material/Cancel';
import { listUsers, updateUser, kickUser } from '../../api/admin';
import type { UserItem, UserAdminUpdate } from '../../types/admin';
import { PageHeader } from '../../components/layout/PageHeader';


const ROLE_LABELS: Record<string, { label: string; color: string }> = {
  patient: { label: '患者', color: '#3B82F6' },
  doctor: { label: '医生', color: '#10B981' },
  admin: { label: '管理员', color: '#EF4444' },
};

const STATUS_LABELS: Record<string, { label: string; color: 'success' | 'error' | 'warning' | 'default' }> = {
  active: { label: '正常', color: 'success' },
  inactive: { label: '禁用', color: 'error' },
  pending: { label: '待审核', color: 'warning' },
};

function getRoleLabel(role: string) {
  return ROLE_LABELS[role]?.label || role;
}

function getRoleColor(role: string) {
  return ROLE_LABELS[role]?.color || '#64748B';
}

function getStatusChip(status: string) {
  const cfg = STATUS_LABELS[status] || { label: status, color: 'default' as const };
  return <Chip size="small" label={cfg.label} color={cfg.color} sx={{ fontWeight: 500 }} />;
}

export default function UsersPage() {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Filters
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  // Edit dialog
  const [openDialog, setOpenDialog] = useState(false);
  const [editingUser, setEditingUser] = useState<UserItem | null>(null);
  const [form, setForm] = useState<UserAdminUpdate>({});
  const [saving, setSaving] = useState(false);

  const [kickOpen, setKickOpen] = useState(false);
  const [kickTarget, setKickTarget] = useState<UserItem | null>(null);
  const [kickReason, setKickReason] = useState('');
  const [kickReasonOther, setKickReasonOther] = useState('');
  const [kicking, setKicking] = useState(false);

  const KICK_REASONS = ['违规发布医疗建议', '滥用平台资源', '发布不当内容', '用户主动要求注销'];

  // 数据获取：内联到 effect 中
  useEffect(() => {
    let cancelled = false;

    startTransition(() => {
      setLoading(true);
      setError('');
    });

    listUsers({
      search: search || undefined,
      role: roleFilter || undefined,
      status: statusFilter || undefined,
      limit: 100,
    })
      .then((data) => {
        if (!cancelled) setUsers(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [search, roleFilter, statusFilter]);

  // 手动刷新
  const handleRefresh = useCallback(() => {
    const cancelled = false;

    startTransition(() => {
      setLoading(true);
      setError('');
    });

    listUsers({
      search: search || undefined,
      role: roleFilter || undefined,
      status: statusFilter || undefined,
      limit: 100,
    })
      .then((data) => {
        if (!cancelled) setUsers(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
  }, [search, roleFilter, statusFilter]);

  const handleOpenEdit = (u: UserItem) => {
    setEditingUser(u);
    setForm({
      full_name: u.full_name,
      status: u.status,
      is_verified: u.is_verified,
      license_number: u.license_number,
      hospital: u.hospital,
      department: u.department,
      title: u.title,
    });
    setOpenDialog(true);
  };

  const handleSave = async () => {
    if (!editingUser) return;
    setSaving(true);
    setError('');
    setSuccess('');
    try {
      await updateUser(editingUser.id, form);
      setSuccess('用户信息已更新');
      setOpenDialog(false);
      handleRefresh();
      setTimeout(() => setSuccess(''), 3000);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleOpenKick = (u: UserItem) => {
    setKickTarget(u);
    setKickReason(KICK_REASONS[0]);
    setKickReasonOther('');
    setKickOpen(true);
  };

  const handleKick = async () => {
    if (!kickTarget) return;
    setKicking(true);
    setError('');
    const reason = kickReason === '其他' ? kickReasonOther : kickReason;
    if (!reason.trim()) { setError('请输入踢出原因'); setKicking(false); return; }
    try {
      const res = await kickUser(kickTarget.id, reason);
      setSuccess(res.email_sent ? '用户已被移除，通知邮件已发送' : '用户已被移除，但通知邮件发送失败');
      setKickOpen(false);
      handleRefresh();
      setTimeout(() => setSuccess(''), 4000);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setKicking(false);
    }
  };

  const isInactive = (u: UserItem) => u.status === 'inactive';

  return (
    <Box>
      <PageHeader title="用户管理" subtitle={`共 ${users.length} 位用户`} />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}
      {success && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess('')}>
          {success}
        </Alert>
      )}

      {/* Filters */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} sx={{ alignItems: 'center' }}>
          <Grid size={{ xs: 12, md: 4 }}>
            <TextField
              size="small"
              fullWidth
              placeholder="搜索邮箱或姓名..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              slotProps={{
                input: {
                  endAdornment: <SearchIcon fontSize="small" color="action" />,
                },
              }}
            />
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <FormControl size="small" fullWidth>
              <InputLabel>角色</InputLabel>
              <Select value={roleFilter} label="角色" onChange={(e) => setRoleFilter(e.target.value)}>
                <MenuItem value="">全部</MenuItem>
                <MenuItem value="patient">患者</MenuItem>
                <MenuItem value="doctor">医生</MenuItem>
                <MenuItem value="admin">管理员</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <FormControl size="small" fullWidth>
              <InputLabel>状态</InputLabel>
              <Select value={statusFilter} label="状态" onChange={(e) => setStatusFilter(e.target.value)}>
                <MenuItem value="">全部</MenuItem>
                <MenuItem value="active">正常</MenuItem>
                <MenuItem value="inactive">禁用</MenuItem>
                <MenuItem value="pending">待审核</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid size={{ xs: 12, md: 2 }}>
            <Button variant="outlined" fullWidth onClick={handleRefresh} disabled={loading}>
              {loading ? <CircularProgress size={16} /> : '刷新'}
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {/* Table */}
      <Card>
        <CardContent sx={{ p: 0 }}>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow sx={{ bgcolor: '#F5F7FA' }}>
                  <TableCell>姓名 / 邮箱</TableCell>
                  <TableCell>角色</TableCell>
                  <TableCell>状态</TableCell>
                  <TableCell>认证</TableCell>
                  <TableCell>医院 / 科室</TableCell>
                  <TableCell>创建时间</TableCell>
                  <TableCell align="right">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  <TableRow>
                    <TableCell colSpan={7} align="center">
                      <CircularProgress size={24} sx={{ my: 2 }} />
                    </TableCell>
                  </TableRow>
                ) : users.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                      暂无用户数据
                    </TableCell>
                  </TableRow>
                ) : (
                  users.map((u) => (
                    <TableRow key={u.id} hover>
                      <TableCell>
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 500 }}>
                            {u.full_name}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {u.email}
                          </Typography>
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={getRoleLabel(u.role)}
                          sx={{
                            bgcolor: getRoleColor(u.role) + '20',
                            color: getRoleColor(u.role),
                            fontWeight: 600,
                          }}
                        />
                      </TableCell>
                      <TableCell>{getStatusChip(u.status)}</TableCell>
                      <TableCell>
                        {u.is_verified ? (
                          <Chip size="small" label="已认证" color="success" variant="outlined" />
                        ) : (
                          <Chip size="small" label="未认证" color="default" variant="outlined" />
                        )}
                      </TableCell>
                      <TableCell>
                        {u.role === 'doctor' ? (
                          <Box>
                            {u.hospital && (
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                {u.hospital}
                              </Typography>
                            )}
                            {u.department && (
                              <Typography variant="caption" color="text.secondary">
                                {u.department} {u.title && `· ${u.title}`}
                              </Typography>
                            )}
                          </Box>
                        ) : (
                          <Typography variant="caption" color="text.secondary">—</Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption" color="text.secondary">
                          {new Date(u.created_at).toLocaleDateString('zh-CN')}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Tooltip title="编辑">
                          <IconButton size="small" onClick={() => handleOpenEdit(u)}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        {u.status !== 'inactive' && (
                          <Tooltip title="踢出">
                            <IconButton size="small" color="error" onClick={() => handleOpenKick(u)}>
                              <CancelIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      {/* Edit Dialog */}
      <Dialog open={openDialog} onClose={() => setOpenDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>编辑用户: {editingUser?.full_name}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <TextField
              label="姓名"
              value={form.full_name || ''}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              size="small"
              fullWidth
            />
            <FormControl size="small" fullWidth>
              <InputLabel>状态</InputLabel>
              <Select
                value={form.status || ''}
                label="状态"
                onChange={(e) => setForm({ ...form, status: e.target.value })}
              >
                <MenuItem value="active">正常</MenuItem>
                <MenuItem value="inactive">禁用</MenuItem>
                <MenuItem value="pending">待审核</MenuItem>
              </Select>
            </FormControl>
            <FormControlLabel
              control={
                <Switch
                  checked={form.is_verified || false}
                  onChange={(e) => setForm({ ...form, is_verified: e.target.checked })}
                />
              }
              label={form.is_verified ? '已认证' : '未认证'}
            />

            {editingUser?.role === 'doctor' && (
              <>
                <Typography variant="subtitle2" sx={{ mt: 1, color: 'text.secondary' }}>
                  医生专属信息
                </Typography>
                <TextField
                  label="执业证号"
                  value={form.license_number || ''}
                  onChange={(e) => setForm({ ...form, license_number: e.target.value || null })}
                  size="small"
                  fullWidth
                />
                <TextField
                  label="所在医院"
                  value={form.hospital || ''}
                  onChange={(e) => setForm({ ...form, hospital: e.target.value || null })}
                  size="small"
                  fullWidth
                />
                <TextField
                  label="科室"
                  value={form.department || ''}
                  onChange={(e) => setForm({ ...form, department: e.target.value || null })}
                  size="small"
                  fullWidth
                />
                <TextField
                  label="职称"
                  value={form.title || ''}
                  onChange={(e) => setForm({ ...form, title: e.target.value || null })}
                  size="small"
                  fullWidth
                />
              </>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenDialog(false)}>取消</Button>
          <Button variant="contained" onClick={handleSave} disabled={saving}>
            {saving ? <CircularProgress size={16} /> : '保存'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={kickOpen} onClose={() => setKickOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ color: 'error.main' }}>
          🚫 踢出用户: {kickTarget?.full_name} ({getRoleLabel(kickTarget?.role || '')})
        </DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              邮箱: {kickTarget?.email}
            </Typography>
            <Divider />
            <Typography variant="body2" sx={{ fontWeight: 600 }}>踢出原因 (必填)</Typography>
            <FormControl fullWidth size="small">
              <Select value={KICK_REASONS.includes(kickReason) ? kickReason : '其他'} onChange={(e) => {
                setKickReason(e.target.value);
                if (e.target.value !== '其他') setKickReasonOther('');
              }}>
                {KICK_REASONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                <MenuItem value="其他">其他 (请输入)</MenuItem>
              </Select>
            </FormControl>
            {kickReason === '其他' && (
              <TextField size="small" fullWidth placeholder="请输入踢出原因" value={kickReasonOther}
                onChange={(e) => setKickReasonOther(e.target.value)} />
            )}
            <Alert severity="warning" sx={{ fontSize: '0.85rem' }}>
              ✉️ 将发送邮件通知用户账户已被移除。该操作不可撤销，用户数据将保留但无法登录。
            </Alert>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setKickOpen(false)}>取消</Button>
          <Button variant="contained" color="error" onClick={handleKick} disabled={kicking}>
            {kicking ? <CircularProgress size={16} /> : '确认踢出并发送邮件'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}