import { useState, useEffect, useCallback } from 'react';
import {
  Box, Container, Paper, Typography, TextField, Button, Alert, CircularProgress,
  Link, ToggleButton, ToggleButtonGroup, InputAdornment, IconButton,
  FormControl, InputLabel, Select, MenuItem, Chip, LinearProgress,
  Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material';
import { Visibility, VisibilityOff, Email, Lock, Person, Phone, LocalHospital } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { register, type RegisterRequest } from '../api/auth';

type Gender = 'male' | 'female';
type Role = 'patient' | 'doctor';

interface ProvinceData { [city: string]: string[] }

interface FormData {
  full_name: string;
  email: string;
  password: string;
  confirmPassword: string;
  role: Role;
  age_years: string;
  age_months: string;
  gender: Gender | '';
  province: string;
  city: string;
  district: string;
  street: string;
  phone: string;
  education: string;
  hospital: string;
  department: string;
  license_number: string;
  title: string;
  years_of_practice: string;
  specialties: string;
  terms: boolean;
}

interface FormErrors { [key: string]: string }

const EDUCATION_OPTIONS = ['高中', '大专', '本科', '硕士', '博士'];
const TITLE_OPTIONS = ['主任医师', '副主任医师', '主治医师', '住院医师'];

function checkPasswordStrength(password: string): { score: number; label: string; color: 'error' | 'warning' | 'success' } {
  let score = 0;
  if (password.length >= 8) score += 1;
  if (password.length >= 12) score += 1;
  if (/[A-Z]/.test(password)) score += 1;
  if (/[a-z]/.test(password)) score += 1;
  if (/[0-9]/.test(password)) score += 1;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;
  if (score <= 2) return { score, label: '弱', color: 'error' };
  if (score <= 4) return { score, label: '中等', color: 'warning' };
  return { score, label: '强', color: 'success' };
}

function validateForm(data: FormData): FormErrors {
  const errors: FormErrors = {};
  if (!data.full_name.trim()) errors.full_name = '请输入姓名';
  if (!data.email.trim()) errors.email = '请输入邮箱地址';
  else if (!/^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i.test(data.email)) errors.email = '请输入有效的邮箱地址';
  if (!data.password) errors.password = '请输入密码';
  else if (data.password.length < 8) errors.password = '密码长度至少为 8 个字符';
  if (!data.confirmPassword) errors.confirmPassword = '请再次输入密码';
  else if (data.password !== data.confirmPassword) errors.confirmPassword = '两次输入的密码不一致';
  if (!data.province) errors.province = '请选择省份';
  if (data.phone && !/^1[3-9]\d{9}$/.test(data.phone)) errors.phone = '请输入有效的手机号码';
  if (data.age_years && (parseInt(data.age_years) < 0 || parseInt(data.age_years) > 120)) errors.age_years = '年龄范围 0-120';
  if (data.role === 'doctor') {
    if (!data.hospital?.trim()) errors.hospital = '请输入执业医院';
    if (!data.department?.trim()) errors.department = '请输入科室';
    if (!data.license_number?.trim()) errors.license_number = '请输入执业证号';
    if (!data.title) errors.title = '请选择职称';
  }
  if (!data.terms) errors.terms = '请同意用户协议和隐私政策';
  return errors;
}

const emptyForm = (role: Role): FormData => ({
  full_name: '', email: '', password: '', confirmPassword: '', role,
  age_years: '', age_months: '', gender: '', province: '', city: '', district: '',
  street: '', phone: '', education: '', hospital: '', department: '',
  license_number: '', title: '', years_of_practice: '', specialties: '', terms: false,
});

export default function RegisterPage() {
  const navigate = useNavigate();
  const [provinceData, setProvinceData] = useState<Record<string, ProvinceData>>({});
  const [formData, setFormData] = useState<FormData>(emptyForm('patient'));
  const [errors, setErrors] = useState<FormErrors>({});
  const [showPwd, setShowPwd] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState('');
  const [termsDialog, setTermsDialog] = useState(false);
  const [privacyDialog, setPrivacyDialog] = useState(false);

  const pwdStrength = checkPasswordStrength(formData.password);
  const strengthPct = Math.min((pwdStrength.score / 6) * 100, 100);
  const isDoctor = formData.role === 'doctor';

  useEffect(() => {
    fetch('/data/pca.json')
      .then((r) => r.json())
      .then(setProvinceData)
      .catch(() => {});
  }, []);

  const provinces = Object.keys(provinceData);
  const cities = formData.province ? Object.keys(provinceData[formData.province] || {}) : [];
  const districts = formData.province && formData.city
    ? (provinceData[formData.province]?.[formData.city] || [])
    : [];

  const setField = useCallback((field: keyof FormData) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setFormData((p) => ({ ...p, [field]: e.target.value }));
    setErrors((p) => { const n = { ...p }; delete n[field]; delete n.general; return n; });
  }, []);

  const setSelectField = useCallback((field: keyof FormData) => (e: { target: { value: string } }) => {
    const val = e.target.value;
    setFormData((p) => {
      const next = { ...p, [field]: val };
      if (field === 'province') { next.city = ''; next.district = ''; }
      if (field === 'city') { next.district = ''; }
      return next;
    });
  }, []);

  const handleRoleChange = useCallback((_: React.MouseEvent, newRole: Role | null) => {
    if (newRole) setFormData(emptyForm(newRole));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ve = validateForm(formData);
    if (Object.keys(ve).length > 0) { setErrors(ve); return; }
    setSubmitting(true);
    setGeneralError('');
    try {
      const payload: RegisterRequest = {
        email: formData.email.trim(),
        password: formData.password,
        role: formData.role,
        full_name: formData.full_name.trim(),
        phone: formData.phone || undefined,
        age_years: formData.age_years ? parseInt(formData.age_years) : null,
        age_months: formData.age_months ? parseInt(formData.age_months) : null,
        gender: formData.gender || null,
        province: formData.province,
        city: formData.city || undefined,
        district: formData.district || undefined,
        street: formData.street || undefined,
        education: formData.education || undefined,
      };
      if (isDoctor) {
        payload.hospital = formData.hospital;
        payload.department = formData.department;
        payload.license_number = formData.license_number;
        payload.title = formData.title;
        payload.years_of_practice = formData.years_of_practice ? parseInt(formData.years_of_practice) : null;
        payload.specialties = formData.specialties || undefined;
      }
      const result = await register(payload);
      if (result.access_token) {
        navigate('/chat', { replace: true });
      } else {
        navigate('/login', { replace: true, state: { message: result.message || '注册成功，请等待管理员审核' } });
      }
    } catch (err) {
      setGeneralError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const textField = (label: string, field: keyof FormData, opts?: { type?: string; placeholder?: string; required?: boolean; autoComplete?: string; multiline?: boolean }) => (
    <TextField
      fullWidth label={label} type={opts?.type || 'text'} placeholder={opts?.placeholder}
      autoComplete={opts?.autoComplete} multiline={opts?.multiline} minRows={opts?.multiline ? 2 : undefined}
      value={String(formData[field] ?? '')} onChange={setField(field)}
      error={!!errors[field]} helperText={errors[field]} disabled={submitting}
      required={opts?.required !== false} sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
    />
  );

  const selectField = (label: string, field: keyof FormData, options: string[], opts?: { required?: boolean }) => (
    <FormControl fullWidth required={opts?.required !== false} sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}>
      <InputLabel>{label}</InputLabel>
      <Select value={String(formData[field])} label={label} onChange={setSelectField(field)} error={!!errors[field]} disabled={submitting}>
        <MenuItem value=""><em>请选择</em></MenuItem>
        {options.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
      </Select>
    </FormControl>
  );

  return (
    <Container maxWidth="sm" sx={{ py: 4 }}>
      <Paper sx={{ p: 4, borderRadius: 3 }}>
        <Typography variant="h5" align="center" gutterBottom sx={{ fontWeight: 700 }}>创建账户</Typography>

        <Box sx={{ display: 'flex', justifyContent: 'center', mb: 3 }}>
          <ToggleButtonGroup value={formData.role} exclusive onChange={handleRoleChange} disabled={submitting}>
            <ToggleButton value="patient" sx={{ px: 4 }}>
              <Person sx={{ mr: 1 }} /> 患者
            </ToggleButton>
            <ToggleButton value="doctor" sx={{ px: 4 }}>
              <LocalHospital sx={{ mr: 1 }} /> 医生
            </ToggleButton>
          </ToggleButtonGroup>
        </Box>

        {generalError && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setGeneralError('')}>{generalError}</Alert>}

        <Box component="form" onSubmit={handleSubmit} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {/* Shared fields */}
          <TextField fullWidth label={isDoctor ? '真实姓名' : '昵称'} placeholder={isDoctor ? '请输入真实姓名' : '请输入昵称'}
            autoComplete="name" value={formData.full_name} onChange={setField('full_name')}
            error={!!errors.full_name} helperText={errors.full_name} disabled={submitting} required
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><Person sx={{ color: 'text.secondary' }} /></InputAdornment> } }}
            sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />

          <TextField fullWidth label="邮箱地址" type="email" placeholder="example@email.com" autoComplete="email"
            value={formData.email} onChange={setField('email')} error={!!errors.email} helperText={errors.email}
            disabled={submitting} required
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><Email sx={{ color: 'text.secondary' }} /></InputAdornment> } }}
            sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />

          <TextField fullWidth label="密码" type={showPwd ? 'text' : 'password'} placeholder="至少 8 位字符" autoComplete="new-password"
            value={formData.password} onChange={setField('password')} error={!!errors.password} helperText={errors.password}
            disabled={submitting} required
            slotProps={{ input: {
              startAdornment: <InputAdornment position="start"><Lock sx={{ color: 'text.secondary' }} /></InputAdornment>,
              endAdornment: <InputAdornment position="end"><IconButton onClick={() => setShowPwd(!showPwd)} edge="end" disabled={submitting}>{showPwd ? <VisibilityOff /> : <Visibility />}</IconButton></InputAdornment>,
            } }}
            sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />

          {formData.password && (
            <Box sx={{ px: 0.5 }}>
              <LinearProgress variant="determinate" value={strengthPct} color={pwdStrength.color} sx={{ height: 6, borderRadius: 3, mb: 0.5 }} />
              <Typography variant="caption" color="text.secondary">密码强度: {pwdStrength.label}</Typography>
            </Box>
          )}

          <TextField fullWidth label="确认密码" type={showConfirm ? 'text' : 'password'} placeholder="请再次输入密码" autoComplete="new-password"
            value={formData.confirmPassword} onChange={setField('confirmPassword')} error={!!errors.confirmPassword} helperText={errors.confirmPassword}
            disabled={submitting} required
            slotProps={{ input: {
              startAdornment: <InputAdornment position="start"><Lock sx={{ color: 'text.secondary' }} /></InputAdornment>,
              endAdornment: <InputAdornment position="end"><IconButton onClick={() => setShowConfirm(!showConfirm)} edge="end" disabled={submitting}>{showConfirm ? <VisibilityOff /> : <Visibility />}</IconButton></InputAdornment>,
            } }}
            sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />

          {/* Age + Gender row */}
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField label="年龄(岁)" type="number" size="small" sx={{ flex: 1, '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
              value={formData.age_years} onChange={setField('age_years')} error={!!errors.age_years} helperText={errors.age_years}
              disabled={submitting} slotProps={{ htmlInput: { min: 0, max: 120 } }} />
            <TextField label="月(可选)" type="number" size="small" sx={{ flex: 1, '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
              value={formData.age_months} onChange={setField('age_months')} disabled={submitting} slotProps={{ htmlInput: { min: 0, max: 11 } }} />
            <FormControl size="small" sx={{ flex: 1 }}>
              <InputLabel>性别</InputLabel>
              <Select value={formData.gender} label="性别" onChange={setSelectField('gender')} disabled={submitting} sx={{ borderRadius: 2 }}>
                <MenuItem value=""><em>不限</em></MenuItem>
                <MenuItem value="male">男</MenuItem>
                <MenuItem value="female">女</MenuItem>
              </Select>
            </FormControl>
          </Box>

          {/* Address cascade */}
          <Box sx={{ display: 'flex', gap: 2 }}>
            {selectField('省/直辖市', 'province', provinces, { required: true })}
            <FormControl fullWidth required sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}>
              <InputLabel>市</InputLabel>
              <Select value={formData.city} label="市" onChange={setSelectField('city')} disabled={submitting || !formData.province} error={!!errors.city}>
                <MenuItem value=""><em>请选择</em></MenuItem>
                {cities.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl fullWidth required sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}>
              <InputLabel>区/县</InputLabel>
              <Select value={formData.district} label="区/县" onChange={setSelectField('district')} disabled={submitting || !formData.city} error={!!errors.district}>
                <MenuItem value=""><em>请选择</em></MenuItem>
                {districts.map((d) => <MenuItem key={d} value={d}>{d}</MenuItem>)}
              </Select>
            </FormControl>
          </Box>

          {textField('街道/详细地址 (可选)', 'street', { required: false })}

          <TextField fullWidth label="手机号 (可选)" placeholder="用于医生联系" autoComplete="tel"
            value={formData.phone} onChange={setField('phone')} error={!!errors.phone} helperText={errors.phone || '仅用于医生联系，不会公开'}
            disabled={submitting}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><Phone sx={{ color: 'text.secondary' }} /></InputAdornment> } }}
            sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />

          {selectField('学历 (可选)', 'education', EDUCATION_OPTIONS, { required: false })}

          {/* Doctor-only fields */}
          {isDoctor && (
            <>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mt: 1, color: '#10B981' }}>执业信息</Typography>
              {textField('执业医院', 'hospital', { placeholder: '如：深圳市人民医院', required: true })}
              {textField('科室', 'department', { placeholder: '如：心血管内科', required: true })}
              {textField('执业证号', 'license_number', { placeholder: '医师执业证书编号', required: true })}
              {selectField('职称', 'title', TITLE_OPTIONS, { required: true })}
              <FormControl fullWidth sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }}>
                <InputLabel>从业年限 (可选)</InputLabel>
                <Select value={formData.years_of_practice} label="从业年限 (可选)" onChange={setSelectField('years_of_practice')} disabled={submitting}>
                  <MenuItem value=""><em>请选择</em></MenuItem>
                  {Array.from({ length: 61 }, (_, i) => <MenuItem key={i} value={String(i)}>{i} 年</MenuItem>)}
                </Select>
              </FormControl>
              <TextField fullWidth label="擅长领域 (可选)" placeholder="如：心血管内科,高血压,冠心病（逗号分隔，最多 5 个）"
                value={formData.specialties} onChange={setField('specialties')} disabled={submitting}
                sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />
              <Alert severity="info" sx={{ fontSize: '0.85rem' }}>
                注册后需上传执业证件并等待管理员审核，审核通过后方可登录医生端。
              </Alert>
            </>
          )}

          {/* Terms */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <input type="checkbox" id="terms" checked={formData.terms} onChange={(e) => { setFormData((p) => ({ ...p, terms: e.target.checked })); }}
              style={{ width: 18, height: 18 }} />
            <Typography variant="body2">
              我已阅读并同意{' '}
              <Link component="button" type="button" onClick={() => setTermsDialog(true)}>用户协议</Link>
              {' '}和{' '}
              <Link component="button" type="button" onClick={() => setPrivacyDialog(true)}>隐私政策</Link>
            </Typography>
          </Box>
          {errors.terms && <Typography variant="caption" color="error">{errors.terms}</Typography>}

          <Button type="submit" variant="contained" fullWidth size="large" disabled={submitting}
            sx={{ mt: 1, py: 1.5, borderRadius: 2, textTransform: 'none', fontSize: '1rem', fontWeight: 600 }}>
            {submitting ? <CircularProgress size={24} sx={{ color: 'white' }} /> : isDoctor ? '提交审核' : '立即注册'}
          </Button>

          <Typography align="center" variant="body2" color="text.secondary">
            已有账号？<Link href="/login">立即登录</Link>
          </Typography>
        </Box>
      </Paper>

      <Dialog open={termsDialog} onClose={() => setTermsDialog(false)}><DialogTitle>用户协议</DialogTitle><DialogContent><Typography>用户协议内容（待补充）</Typography></DialogContent><DialogActions><Button onClick={() => setTermsDialog(false)}>关闭</Button></DialogActions></Dialog>
      <Dialog open={privacyDialog} onClose={() => setPrivacyDialog(false)}><DialogTitle>隐私政策</DialogTitle><DialogContent><Typography>隐私政策内容（待补充）</Typography></DialogContent><DialogActions><Button onClick={() => setPrivacyDialog(false)}>关闭</Button></DialogActions></Dialog>
    </Container>
  );
}
