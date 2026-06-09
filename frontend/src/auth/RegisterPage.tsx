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

      <Dialog open={termsDialog} onClose={() => setTermsDialog(false)} maxWidth="md" fullWidth scroll="paper">
        <DialogTitle sx={{ bgcolor: 'primary.main', color: 'white' }}>用户服务协议</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" paragraph sx={{ color: 'text.secondary', fontSize: '0.75rem' }}>
            最后更新日期：2025年2月
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', color: 'error.main' }}>
            重要提示
          </Typography>
          <Typography variant="body2" paragraph>
            欢迎使用 MediCareAI（以下简称"本服务"）！本协议是您（以下简称"用户"）与本服务提供方（以下简称"我们"）之间就使用 MediCareAI 服务所订立的协议。请您在使用本服务前仔细阅读并充分理解本协议的全部内容。当您点击"同意"按钮、注册账号或以其他任何方式使用本服务时，即表示您已阅读、理解并同意接受本协议的全部约束。若您不同意本协议的任何内容，请勿使用本服务。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第一条 术语定义
          </Typography>
          <Typography variant="body2" paragraph>
            1.1 <strong>本服务</strong>：指由我们开发、运营的基于人工智能的智能疾病管理系统，包括但不限于患者档案管理、AI智能诊断、文档智能处理、医疗记录管理、知识库系统、医生协作平台等功能模块。<br /><br />
            1.2 <strong>用户</strong>：指注册、登录并使用本服务的自然人、医疗机构或组织。<br /><br />
            1.3 <strong>患者</strong>：指其个人信息和健康数据被录入本系统进行管理的自然人。<br /><br />
            1.4 <strong>医生</strong>：指经过我们认证审核，具备相应医疗资质的专业医师。<br /><br />
            1.5 <strong>管理员</strong>：指负责系统运营、管理、监控及知识库维护的我们授权人员。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第二条 协议的接受与适用
          </Typography>
          <Typography variant="body2" paragraph>
            2.1 <strong>协议的接受</strong>：您通过点击"同意"按钮、注册账号或以其他任何方式使用本服务，即视为您已充分阅读、理解并同意接受本协议的全部内容。<br /><br />
            2.2 <strong>协议更新</strong>：我们有权根据法律法规变化、技术发展及业务需要，对本协议进行修改。修改后的协议将在本平台公布，一经公布即生效。您继续使用本服务，视为您接受修改后的协议。<br /><br />
            2.3 <strong>单独协议</strong>：本协议为用户服务协议，与本服务同时提供的《隐私保护政策》及其他相关规则共同构成您与我们之间的完整协议。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第三条 用户注册与账号管理
          </Typography>
          <Typography variant="body2" paragraph>
            3.1 <strong>注册要求</strong>：用户注册时应当提供真实、准确、完整的信息，包括但不限于真实姓名、身份证号码、联系方式等。如提供的信息不真实、不准确或不完整，我们将有权暂停或终止您的账号使用权。<br /><br />
            3.2 <strong>账号安全</strong>：用户应当妥善保管账号及密码，因您保管不善可能导致账号被盗用。您对以其账号进行的所有活动负责。<br /><br />
            3.3 <strong>账号权限</strong>：本服务支持患者、医生、管理员三种用户角色，不同角色拥有不同的权限。<br /><br />
            3.4 <strong>账号注销</strong>：您可随时申请注销账号。账号注销后，您的个人信息将被删除或匿名化处理，但法律法规另有规定的除外。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第四条 用户个人信息保护
          </Typography>
          <Typography variant="body2" paragraph>
            4.1 <strong>信息收集范围</strong>：根据《中华人民共和国个人信息保护法》及《中华人民共和国民法典》的相关规定，我们可能会收集身份信息、联系方式、生物识别信息、健康信息、文档信息等。<br /><br />
            4.2 <strong>敏感个人信息处理</strong>：健康信息属于《个人信息保护法》规定的"敏感个人信息"。处理敏感个人信息，应当取得您的单独同意，并采取严格保护措施。<br /><br />
            4.3 <strong>信息使用目的</strong>：我们收集和使用您的信息，仅用于提供AI智能诊断服务、完善患者档案和病史记录、实现疾病追踪和随访管理、医生诊疗辅助和协作、改进服务质量。未经您同意，我们不会将您的个人信息用于与上述目的无关的其他用途。<br /><br />
            4.4 <strong>信息共享与披露</strong>：除获得您的明确同意、为完成服务所必需的第三方服务提供商、依法向有关主管部门报告或配合执法机关查询、为维护公共利益或国家利益所必需的情况外，我们不会向第三方共享您的个人信息。<br /><br />
            4.5 <strong>信息存储与安全</strong>：我们将在法律法规规定的期限内保存您的个人信息，采用加密、脱敏等技术手段保护您的信息安全，定期进行安全审计和风险评估，建立应急响应机制，防范数据泄露风险。<br /><br />
            4.6 <strong>您的权利</strong>：根据《个人信息保护法》的规定，您享有访问权、更正权、删除权、撤回同意权、注销账号权。<br /><br />
            4.7 <strong>未成年人保护</strong>：我们非常重视对未成年人的保护。如您是未成年人，请在监护人的陪同下使用本服务。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第五条 用户行为规范
          </Typography>
          <Typography variant="body2" paragraph>
            5.1 <strong>合法合规使用</strong>：您应当遵守国家法律法规，不得利用本服务从事传播违法、不良信息，侵犯他人知识产权或其他合法权益，进行网络攻击、黑客行为，恶意注册账号、刷量作弊等行为。<br /><br />
            5.2 <strong>内容真实性</strong>：您上传的病历资料、诊断信息等应当真实、准确。如因信息不实导致损害，您应承担相应责任。<br /><br />
            5.3 <strong>不得滥用AI功能</strong>：您不得利用AI诊断功能进行欺诈、误导或其他不当目的。<br /><br />
            5.4 <strong>不得传播AI诊断结果</strong>：AI诊断结果仅供参考，不得作为医疗诊断的唯一依据，不得用于医疗纠纷中的不当用途。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第六条 知识产权声明
          </Typography>
          <Typography variant="body2" paragraph>
            6.1 <strong>软件知识产权</strong>：本服务的软件、代码、文档、数据等知识产权归我们或相关权利人所有，受《中华人民共和国著作权法》、《中华人民共和国专利法》等法律保护。<br /><br />
            6.2 <strong>用户内容归属</strong>：您上传至本服务的文档、病历资料等内容的知识产权归您或相关权利人所有。您授予我们在本服务范围内非独家、免费的使用许可。<br /><br />
            6.3 <strong>禁止反向工程</strong>：您不得对本软件进行反向工程、反编译、反汇编或其他逆向操作。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2, color: 'error.main' }}>
            第七条 免责声明与责任限制（重要）
          </Typography>
          <Typography variant="body2" paragraph>
            7.1 <strong>AI诊断免责声明</strong>：<br />
            • AI诊断结果仅供参考，不构成正式医疗诊断<br />
            • AI系统可能存在误诊、漏诊风险，不承担医疗损害赔偿责任<br />
            • 重大疾病诊断应以专业医生的诊断为准<br />
            • 您使用AI诊断结果产生的任何后果由您自行承担<br /><br />
            7.2 <strong>服务中断与故障</strong>：因不可抗力（包括但不限于自然灾害、政府行为、网络故障等）导致的服务中断，我们不承担责任。因用户设备问题或网络原因导致的服务异常，我们不承担责任。我们不保证服务连续性、稳定性和无错误。<br /><br />
            7.3 <strong>第三方服务免责</strong>：本服务可能使用第三方服务，如阿里云OSS、OpenAI API等。对于第三方服务的质量、安全、合规性，我们不承担任何责任。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第八条 争议解决
          </Typography>
          <Typography variant="body2" paragraph>
            8.1 <strong>法律适用</strong>：本协议的订立、执行、解释及争议解决均适用中华人民共和国法律。<br /><br />
            8.2 <strong>争议解决方式</strong>：双方应友好协商解决；协商不成的，任何一方均可向本服务提供方所在地人民法院提起诉讼。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2, color: 'warning.main' }}>
            特别提示
          </Typography>
          <Typography variant="body2" paragraph>
            1. MediCareAI 是医疗辅助工具，AI诊断结果仅供参考，不替代专业医生的诊断<br />
            2. 您上传的所有文档和医疗信息将受到严格保护，我们将按照法律法规要求进行处理<br />
            3. 使用本服务即表示您理解并接受以上条款<br /><br />
            如对本协议有任何疑问，请联系我们：邮箱：hougelangley1987@gmail.com
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTermsDialog(false)} variant="contained">我已阅读并理解</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={privacyDialog} onClose={() => setPrivacyDialog(false)} maxWidth="md" fullWidth scroll="paper">
        <DialogTitle sx={{ bgcolor: 'secondary.main', color: 'white' }}>隐私保护政策</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" paragraph sx={{ color: 'text.secondary', fontSize: '0.75rem' }}>
            最后更新日期：2025年2月
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', color: 'primary.main' }}>
            欢迎使用 MediCareAI（以下简称"我们"或"本服务"）！
          </Typography>
          <Typography variant="body2" paragraph>
            我们深知个人信息对您的重要性，并将按照法律法规的要求，采取相应的安全保护措施，尽力保护您的个人信息安全可控。本隐私政策将帮助您了解我们如何收集、使用、存储、保护您的个人信息。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第一条 政策更新与生效
          </Typography>
          <Typography variant="body2" paragraph>
            1.1 <strong>政策更新</strong>：我们有权根据法律法规变化、业务发展及技术进步，对本隐私政策进行修改。修改后的隐私政策将在本平台公布，一经公布即生效。<br /><br />
            1.2 <strong>继续使用即视为同意</strong>：如果您不同意修改后的隐私政策内容，您有权停止使用本服务；如果您继续使用本服务，则视为您同意接受修改后的隐私政策。<br /><br />
            1.3 <strong>生效日期</strong>：本隐私政策自 2025年2月20日 起生效。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第二条 我们如何收集和使用您的个人信息
          </Typography>
          <Typography variant="body2" paragraph>
            2.1 <strong>信息收集范围</strong>：根据《中华人民共和国个人信息保护法》及《中华人民共和国民法典》的相关规定，我们可能会收集以下信息：<br /><br />
            <strong>身份信息</strong>：真实姓名、身份证号码、出生日期、性别等（用于用户身份认证、服务提供、法律合规要求）<br /><br />
            <strong>联系信息</strong>：手机号码、电子邮箱、地址等（用于服务通知、沟通联系、身份验证）<br /><br />
            <strong>生物识别信息</strong>：指纹、面部特征等（如适用，用于设备识别、安全验证、防止账号被盗用）<br /><br />
            <strong style={{color: 'error.main'}}>健康信息</strong>：病历、诊断结果、症状描述、病史、用药记录等（用于AI智能诊断、疾病管理、随访计划、病史追踪）<br /><br />
            <strong>文档信息</strong>：上传的病历资料、检查报告、影像资料等（用于疾病追踪、健康管理、AI辅助诊断）<br /><br />
            <strong>设备与网络信息</strong>：设备型号、操作系统、IP地址、使用日志等（用于设备兼容性、用户体验优化、安全防护）
          </Typography>

          <Typography variant="body2" paragraph>
            2.2 <strong>信息使用目的</strong>：我们收集和使用您的个人信息，仅用于以下目的：<br />
            • 提供AI智能诊断服务<br />
            • 完善患者档案和病史记录<br />
            • 实现疾病追踪和随访管理<br />
            • 医生诊疗辅助和协作<br />
            • 改进服务质量<br />
            • 安全防护<br />
            • 法律合规<br /><br />
            未经您同意，我们不会将您的个人信息用于与上述目的无关的其他用途。
          </Typography>

          <Typography variant="body2" paragraph>
            2.3 <strong>不收集的信息</strong>：我们不会主动收集您的银行卡、支付账户等敏感金融信息；您的浏览记录、消费习惯等行为数据；您的社交关系、通讯录等非必要信息。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2, color: 'error.main' }}>
            第三条 敏感个人信息特别说明
          </Typography>
          <Typography variant="body2" paragraph>
            3.1 <strong>什么是敏感个人信息？</strong>：根据《个人信息保护法》第二十八条，敏感个人信息是指一旦泄露或者非法使用，可能导致自然人的人格尊严受到侵害或者人身、财产安全受到危害的个人信息，包括生物识别、宗教信仰、特定身份、医疗健康、金融账户、行踪轨迹等信息，以及不满十四周岁未成年人的个人信息。
          </Typography>

          <Typography variant="body2" paragraph>
            3.2 <strong>医疗健康信息的特殊保护</strong>：健康信息属于敏感个人信息，处理敏感个人信息应当具备以下条件：<br />
            • 取得您的<strong>单独同意</strong><br />
            • 具有特定的目的和充分的必要性<br />
            • 对该类个人信息进行严格保护
          </Typography>

          <Typography variant="body2" paragraph>
            3.3 <strong>敏感信息处理原则</strong>：<br />
            • <strong>单独同意原则</strong>：在收集前会明确告知您，并取得您的单独同意<br />
            • <strong>最小必要原则</strong>：仅收集实现服务功能所必需的最小范围信息<br />
            • <strong>明确告知原则</strong>：会在收集前明确告知信息收集的目的、方式和范围<br />
            • <strong>严格保护原则</strong>：采用加密、脱敏、访问控制等技术措施严格保护<br />
            • <strong>用途限定原则</strong>：严格限定在医疗健康相关用途范围内使用
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第四条 我们如何共享、转让、公开披露您的个人信息
          </Typography>
          <Typography variant="body2" paragraph>
            4.1 <strong>共享</strong>：我们不会与任何公司、组织和个人共享您的个人信息，除非：<br />
            • <strong>获得您的明确同意</strong><br />
            • <strong>为完成服务所必需</strong>：与提供技术支持的第三方服务提供商共享（如阿里云OSS、OpenAI API等）<br />
            • <strong>为履行法定职责</strong>：依法向有关主管部门报告或配合执法机关查询<br />
            • <strong>为维护公共利益</strong>：为维护公共利益或国家利益所必需<br />
            • <strong>与授权合作伙伴共享</strong>：在获得您授权后，与授权合作伙伴（如医疗机构）共享
          </Typography>

          <Typography variant="body2" paragraph>
            4.2 <strong>转让</strong>：我们不会将您的个人信息转让给任何公司、组织和个人，除非获得您的同意、发生合并收购（我们会向您告知新的接收方，并要求其继续履行本隐私政策）或法律法规规定的情况。
          </Typography>

          <Typography variant="body2" paragraph>
            4.3 <strong>公开披露</strong>：我们仅会在获得您明确同意或法律法规规定的情况下公开披露您的个人信息。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第五条 我们如何存储您的个人信息
          </Typography>
          <Typography variant="body2" paragraph>
            5.1 <strong>存储地点</strong>：<br />
            • <strong>一般个人信息</strong>：中华人民共和国境内服务器<br />
            • <strong>敏感个人信息</strong>：在中华人民共和国境内存储，法律法规另有规定的除外
          </Typography>

          <Typography variant="body2" paragraph>
            5.2 <strong>存储期限</strong>：<br />
            • <strong>身份信息</strong>：为提供和保障服务所必需，最长不超过您注销账号后1年<br />
            • <strong>健康信息</strong>：为提供和保障服务所必需，最长不超过您注销账号后5年<br />
            • <strong>使用日志</strong>：为维护服务安全所必需，保存期限不少于6个月<br />
            • <strong>其他信息</strong>：当您停止使用本服务时，我们会及时删除或匿名化处理
          </Typography>

          <Typography variant="body2" paragraph>
            5.3 <strong>存储安全措施</strong>：<br />
            • <strong>加密存储</strong>：敏感信息采用加密方式存储<br />
            • <strong>访问控制</strong>：实施严格的访问权限管理，仅授权人员可访问<br />
            • <strong>安全审计</strong>：定期进行安全审计和风险评估<br />
            • <strong>数据备份</strong>：定期对重要数据进行备份<br />
            • <strong>应急响应</strong>：建立数据泄露应急响应机制
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第六条 您的权利
          </Typography>
          <Typography variant="body2" paragraph>
            根据《个人信息保护法》的规定，您享有以下权利：
          </Typography>

          <Typography variant="body2" paragraph>
            6.1 <strong>访问权</strong>：您有权访问您的个人信息，包括您的基本信息、健康档案和病历信息、文档上传记录、使用日志。您可以在"设置"或"个人中心"中查看和导出您的个人信息。
          </Typography>

          <Typography variant="body2" paragraph>
            6.2 <strong>更正权</strong>：您有权更正不准确或不完整的个人信息。您可以在"设置"或"个人中心"中修改您的个人信息。
          </Typography>

          <Typography variant="body2" paragraph>
            6.3 <strong>删除权</strong>：在以下情形中，您可以要求删除您的个人信息：不再使用本服务、提供的目的实现、您撤回同意、法律规定的删除情形。您可在"设置"→"账号管理"→"申请删除"中提交申请，我们将在15个工作日内处理。
          </Typography>

          <Typography variant="body2" paragraph>
            6.4 <strong>撤回同意权</strong>：您有权随时撤回对个人信息处理的同意。您可以在"设置"→"隐私设置"中撤回同意，或通过 hougelangley1987@gmail.com 联系我们。
          </Typography>

          <Typography variant="body2" paragraph>
            6.5 <strong>注销账号权</strong>：您有权随时申请注销账号。您可在"设置"→"账号管理"→"注销账号"中提交申请。账号注销后，您的个人信息将被删除或匿名化处理，且无法恢复。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第七条 未成年人信息保护
          </Typography>
          <Typography variant="body2" paragraph>
            7.1 <strong>定义</strong>：不满十四周岁的未成年人为儿童，其个人信息为儿童个人信息。
          </Typography>

          <Typography variant="body2" paragraph>
            7.2 <strong>保护原则</strong>：我们非常重视对未成年人的保护，处理儿童个人信息时将遵循以下原则：<br />
            • <strong>专门保护</strong>：采取专门的保护措施保护儿童个人信息<br />
            • <strong>家长同意</strong>：处理儿童个人信息应当取得其监护人的同意<br />
            • <strong>最小收集</strong>：仅收集实现服务功能所必需的最小范围信息
          </Typography>

          <Typography variant="body2" paragraph>
            7.3 <strong>儿童信息处理</strong>：我们不会主动收集未成年人的个人信息，特别是敏感的健康信息。如发现已收集未成年人的个人信息，我们将尽快删除。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第八条 数据跨境传输
          </Typography>
          <Typography variant="body2" paragraph>
            8.1 <strong>数据本地化存储</strong>：根据《个人信息保护法》第三十八条的规定，我们目前将所有个人信息存储在中华人民共和国境内服务器。
          </Typography>

          <Typography variant="body2" paragraph>
            8.2 <strong>数据出境情形</strong>：如需将个人信息传输至境外，我们将：<br />
            • 取得您的单独同意<br />
            • 通过国家网信部门组织的安全评估<br />
            • 签订个人信息出境标准合同<br />
            • 通过个人信息保护认证<br />
            • 通过专业机构进行个人信息保护认证
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第九条 响应您的请求
          </Typography>
          <Typography variant="body2" paragraph>
            9.1 <strong>请求处理流程</strong>：<br />
            • 验证您的身份和权限<br />
            • 核实您请求的合理性<br />
            • 按照法律法规要求处理您的请求<br />
            • 将处理结果通知您
          </Typography>

          <Typography variant="body2" paragraph>
            9.2 <strong>处理时限</strong>：<br />
            • <strong>访问权、更正权、删除权</strong>：15个工作日内<br />
            • <strong>其他请求</strong>：30个工作日内
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第十条 Cookie 和类似技术的使用
          </Typography>
          <Typography variant="body2" paragraph>
            我们使用 Cookie 和类似技术用于用户识别、安全防护、统计分析、功能实现。您可以通过浏览器设置拒绝或删除 Cookie，但拒绝 Cookie 可能会影响本服务的正常使用。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第十一条 第三方服务说明
          </Typography>
          <Typography variant="body2" paragraph>
            本服务可能使用以下第三方服务：<br />
            • <strong>阿里云</strong>：对象存储服务（OSS），用于存储用户上传的文档<br />
            • <strong>OpenAI</strong>：AI大模型服务，用于AI智能诊断功能<br />
            • <strong>其他服务</strong>：技术支持、云服务等
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第十二条 您的个人信息安全
          </Typography>
          <Typography variant="body2" paragraph>
            12.1 <strong>安全措施</strong>：我们采用加密技术（SSL加密、数据加密）、访问控制、安全审计、安全培训、应急响应机制等措施保护您的个人信息安全。
          </Typography>

          <Typography variant="body2" paragraph>
            12.2 <strong>数据泄露通知</strong>：如发生个人信息泄露事件，我们将立即启动应急预案，向监管部门报告，通知您（如可能对您造成风险），并采取补救措施。
          </Typography>

          <Typography variant="body1" paragraph sx={{ fontWeight: 'bold', mt: 2 }}>
            第十三条 联系我们
          </Typography>
          <Typography variant="body2" paragraph>
            如您对本隐私政策有任何疑问、意见或建议，或需要行使您的个人信息相关权利，请通过以下方式联系我们：<br /><br />
            <strong>电子邮件</strong>：hougelangley1987@gmail.com<br /><br />
            我们将在收到您的请求后15个工作日内回复您。
          </Typography>

          <Typography variant="body2" paragraph sx={{ mt: 2, fontStyle: 'italic' }}>
            感谢您对 MediCareAI 的信任与支持！
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPrivacyDialog(false)} variant="contained">我已阅读并理解</Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}
