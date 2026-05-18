import { useEffect, useState } from 'react';
import { Box, Typography, Button, LinearProgress, Paper, keyframes } from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import HourglassBottomIcon from '@mui/icons-material/HourglassBottom';
import ScienceIcon from '@mui/icons-material/Science';
import TipsAndUpdatesIcon from '@mui/icons-material/TipsAndUpdates';
import CloseIcon from '@mui/icons-material/Close';
import IconButton from '@mui/material/IconButton';

interface UploadItem {
  fileId: string;
  fileName: string;
  status: 'parsing' | 'completed' | 'failed';
}

interface Props {
  uploads: UploadItem[];
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

export default function UploadStatusBanner({ uploads, onDismiss }: Props) {
  const [readyVisible, setReadyVisible] = useState(false);

  const hasParsing = uploads.some((u) => u.status === 'parsing');
  const completedCount = uploads.filter((u) => u.status === 'completed').length;
  const allDone = uploads.length > 0 && uploads.every((u) => u.status !== 'parsing');

  useEffect(() => {
    if (allDone && uploads.length > 0) {
      setReadyVisible(true);
      const timer = setTimeout(() => {
        setReadyVisible(false);
        onDismiss();
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [allDone, uploads.length, onDismiss]);

  useEffect(() => {
    if (hasParsing) {
      setReadyVisible(false);
    }
  }, [hasParsing]);

  if (uploads.length === 0 && !readyVisible) return null;

  // State C: ready — all reports parsed
  if (readyVisible && allDone) {
    return (
      <Paper
        elevation={0}
        sx={{
          mx: 2,
          mb: 1.5,
          p: 2,
          borderRadius: 3,
          background: 'linear-gradient(135deg, #E8F5E9 0%, #F1F8E9 100%)',
          border: '1px solid #A5D6A7',
          animation: `${fadeInUp} 0.35s ease-out`,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
          <CheckCircleOutlineIcon sx={{ color: '#2E7D32', mt: 0.3, fontSize: 22 }} />
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

  // State B: parsing in progress
  if (hasParsing) {
    const progress = uploads.length > 0 ? (completedCount / uploads.length) * 100 : 0;
    return (
      <Paper
        elevation={0}
        sx={{
          mx: 2,
          mb: 1.5,
          p: 2,
          borderRadius: 3,
          background: 'linear-gradient(135deg, #FFF8E1 0%, #FFF3E0 100%)',
          border: '1px solid #FFE082',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
          <ScienceIcon sx={{ color: '#E65100', animation: `${pulse} 1.5s ease-in-out infinite`, fontSize: 20 }} />
          <Typography variant="body2" sx={{ color: '#BF360C', fontWeight: 600 }}>
            正在解读您上传的 {uploads.length} 份报告
          </Typography>
        </Box>

        <LinearProgress
          variant="determinate"
          value={progress}
          sx={{
            mb: 1.5,
            height: 6,
            borderRadius: 3,
            bgcolor: '#FFECB3',
            '& .MuiLinearProgress-bar': {
              borderRadius: 3,
              background: 'linear-gradient(90deg, #FF8F00, #FF6F00)',
            },
          }}
        />

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, mb: 1 }}>
          {uploads.map((u) => (
            <Box key={u.fileId} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {u.status === 'completed' ? (
                <CheckCircleOutlineIcon sx={{ color: '#2E7D32', fontSize: 16 }} />
              ) : u.status === 'failed' ? (
                <CloseIcon sx={{ color: '#C62828', fontSize: 16 }} />
              ) : (
                <HourglassBottomIcon sx={{ color: '#E65100', fontSize: 16, animation: `${pulse} 1.5s ease-in-out infinite` }} />
              )}
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

  // State A: idle — subtle reminder
  return (
    <Paper
      elevation={0}
      sx={{
        mx: 2,
        mb: 1.5,
        p: 1.5,
        borderRadius: 3,
        background: '#F3F8FD',
        border: '1px solid #BBDEFB',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <TipsAndUpdatesIcon sx={{ color: '#1565C0', fontSize: 18 }} />
        <Typography variant="body2" sx={{ color: '#0D47A1', flex: 1 }}>
          如有新的检查报告，建议先上传，等待解读完成后再提问，分析会更全面
        </Typography>
        <IconButton size="small" onClick={onDismiss} sx={{ color: '#1565C0', p: 0.5 }}>
          <CloseIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </Box>
    </Paper>
  );
}
