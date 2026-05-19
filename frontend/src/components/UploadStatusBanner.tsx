import { useEffect, useState } from 'react';
import { Box, Typography, Button, LinearProgress, Paper, keyframes, IconButton } from '@mui/material';
import { uploadTokens } from '../theme/uploadTokens';

interface UploadItem {
  fileId: string;
  fileName: string;
  status: 'parsing' | 'completed' | 'failed';
}

interface Props {
  uploads: UploadItem[];
  failedAttempts: Map<string, number>;
  mode: 'consulting' | 'diagnosed';
  onDismiss: () => void;
}

const pulse = keyframes`
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
`;

const fadeInUp = keyframes`
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
`;

export default function UploadStatusBanner({ uploads, failedAttempts, mode, onDismiss }: Props) {
  const [readyVisible, setReadyVisible] = useState(false);

  const hasParsing = uploads.some((u) => u.status === 'parsing');
  const completedCount = uploads.filter((u) => u.status === 'completed').length;
  const failedUploads = uploads.filter((u) => u.status === 'failed');
  const hasFailures = failedUploads.length > 0;
  const allDone = uploads.length > 0 && uploads.every((u) => u.status !== 'parsing');

  const persistentFailures = failedUploads.filter(
    (u) => (failedAttempts.get(u.fileName) || 0) >= 2
  );

  useEffect(() => {
    if (allDone && uploads.length > 0) {
      setReadyVisible(true);
      const timer = setTimeout(() => {
        setReadyVisible(false);
        onDismiss();
      }, mode === 'diagnosed' ? 5000 : 3000);
      return () => clearTimeout(timer);
    }
  }, [allDone, uploads.length, onDismiss]);

  useEffect(() => {
    if (hasParsing) {
      setReadyVisible(false);
    }
  }, [hasParsing]);

  if (uploads.length === 0 && !readyVisible) return null;

  // State D: persistent failure — same file failed 2+ times
  if (persistentFailures.length > 0) {
    return (
      <Paper
        elevation={0}
        sx={{
          mx: 2, mb: 1.5, p: 2, borderRadius: 3,
          background: 'linear-gradient(135deg, #FFEBEE 0%, #FCE4EC 100%)',
          border: '1px solid #EF9A9A',
          animation: `${fadeInUp} 0.35s ease-out`,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
          <Typography sx={{ fontSize: 22, lineHeight: 1 }}>🚨</Typography>
          <Box sx={{ flex: 1 }}>
            <Typography variant="body2" sx={{ color: '#B71C1C', fontWeight: 600, mb: 0.5 }}>
              报告持续解析失败
            </Typography>
            <Typography variant="caption" sx={{ color: '#C62828' }}>
              AI 服务可能异常。请立即携带原始报告就医，由医生直接解读。
            </Typography>
          </Box>
          <Button
            size="small"
            onClick={() => { setReadyVisible(false); onDismiss(); }}
            sx={{ minWidth: 56, fontSize: 12, color: '#B71C1C', textTransform: 'none', whiteSpace: 'nowrap' }}
          >
            我知道了
          </Button>
        </Box>
      </Paper>
    );
  }

  // State C: ready — all reports parsed, no failures
  if (readyVisible && allDone && !hasFailures) {
    return (
      <Paper
        elevation={0}
        sx={{
          mx: 2, mb: 1.5, p: 2, borderRadius: 3,
          background: 'linear-gradient(135deg, #E8F5E9 0%, #F1F8E9 100%)',
          border: '1px solid #A5D6A7',
          animation: `${fadeInUp} 0.35s ease-out`,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
          <Typography sx={{ fontSize: 22, lineHeight: 1 }}>✅</Typography>
          <Box sx={{ flex: 1 }}>
            <Typography variant="body2" sx={{ color: '#1B5E20', fontWeight: 600, mb: 0.3 }}>
              {completedCount} 份报告已解读完成
            </Typography>
            <Typography variant="caption" sx={{ color: '#388E3C' }}>
              请描述您的问题，我将结合所有检查结果为您分析
            </Typography>
          </Box>
          <Button
            size="small"
            onClick={() => { setReadyVisible(false); onDismiss(); }}
            sx={{ minWidth: 48, fontSize: 12, color: '#2E7D32', textTransform: 'none', whiteSpace: 'nowrap' }}
          >
            好的
          </Button>
        </Box>
      </Paper>
    );
  }

  // State C-partial: all done but some failures
  if (allDone && hasFailures && !hasParsing) {
    return (
      <Paper
        elevation={0}
        sx={{
          mx: 2, mb: 1.5, p: 2, borderRadius: 3,
          background: 'linear-gradient(135deg, #FFF3E0 0%, #FBE9E7 100%)',
          border: '1px solid #FFAB91',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
          <Typography sx={{ fontSize: 22, lineHeight: 1 }}>⚠️</Typography>
          <Box sx={{ flex: 1 }}>
            <Typography variant="body2" sx={{ color: '#BF360C', fontWeight: 600, mb: 0.3 }}>
              {completedCount} 份成功，{failedUploads.length} 份失败
            </Typography>
            <Typography variant="caption" sx={{ color: '#E65100' }}>
              请使用下方 📎 按钮重新上传失败的报告后再提问
            </Typography>
          </Box>
          <Button
            size="small"
            onClick={() => { setReadyVisible(false); onDismiss(); }}
            sx={{ minWidth: 48, fontSize: 12, color: '#BF360C', textTransform: 'none', whiteSpace: 'nowrap' }}
          >
            好的
          </Button>
        </Box>
      </Paper>
    );
  }

  // State B: parsing in progress
  if (hasParsing) {
    const progress = uploads.length > 0 ? (completedCount / uploads.length) * 100 : 0;
    return (
      <Paper
        elevation={0}
        sx={{
          mx: 2, mb: 1.5, p: 2, borderRadius: 3,
          background: 'linear-gradient(135deg, #FFF8E1 0%, #FFF3E0 100%)',
          border: '1px solid #FFE082',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
          <Typography
            sx={{
              fontSize: 20,
              animation: `${pulse} 1.5s ease-in-out infinite`,
            }}
          >
            🔬
          </Typography>
          <Typography variant="body2" sx={{ color: '#BF360C', fontWeight: 600 }}>
            正在解读您上传的 {uploads.length} 份报告
          </Typography>
        </Box>

        <LinearProgress
          variant="determinate"
          value={progress}
          sx={{
            mb: 1.5, height: 6, borderRadius: 3, bgcolor: '#FFECB3',
            '& .MuiLinearProgress-bar': {
              borderRadius: 3,
              background: 'linear-gradient(90deg, #FF8F00, #FF6F00)',
            },
          }}
        />

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, mb: 1 }}>
          {uploads.map((u) => (
            <Box key={u.fileId} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography sx={{ fontSize: 14 }}>
                {u.status === 'completed' ? '✅' : u.status === 'failed' ? '❌' : '🔄'}
              </Typography>
              <Typography variant="caption" sx={{ color: u.status === 'failed' ? '#C62828' : '#5D4037' }}>
                📄 {u.fileName}
                {u.status === 'completed' && ' — 已解读'}
                {u.status === 'parsing' && ' — 解读中'}
                {u.status === 'failed' && ' — 失败'}
              </Typography>
            </Box>
          ))}
        </Box>

        <Typography variant="caption" sx={{ color: '#8D6E63', fontStyle: 'italic' }}>
          请稍候，解读完成后提问效果更好哦～
        </Typography>
      </Paper>
    );
  }

  // State A: idle — subtle reminder (diagnosed mode only)
  if (mode !== 'diagnosed') return null;

  return (
    <Paper
      elevation={0}
      sx={{
        mx: 2, mb: 1.5, p: 1.5, borderRadius: `${uploadTokens.radius}px`,
        background: uploadTokens.idle.bg, border: `1px solid ${uploadTokens.idle.border}`,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography sx={{ fontSize: 16 }}>💡</Typography>
        <Typography variant="body2" sx={{ color: '#0D47A1', flex: 1 }}>
          如有新的检查报告，建议先上传，等待解读完成后再提问，分析会更全面
        </Typography>
        <IconButton size="small" onClick={onDismiss} sx={{ color: '#1565C0', p: 0.5 }}>
          <Typography sx={{ fontSize: 14, lineHeight: 1 }}>✕</Typography>
        </IconButton>
      </Box>
    </Paper>
  );
}
