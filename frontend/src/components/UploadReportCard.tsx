import { useState } from 'react';
import { Box, Typography, Paper, keyframes, Button } from '@mui/material';
import type { LabReportResult } from '../types/agent';
import LabReportCard from './LabReportCard';
import { uploadTokens } from '../theme/uploadTokens';

interface Props {
  fileName: string;
  status: 'parsing' | 'completed' | 'failed';
  report?: LabReportResult;
  error?: string;
}

const pulse = keyframes`
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
`;

export default function UploadReportCard({ fileName, status, report, error }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (status === 'parsing') {
    return (
      <Paper
        elevation={0}
        sx={{
          mx: 2, my: 1, p: 1.5,
          borderRadius: uploadTokens.radius,
          background: uploadTokens.parsing.gradient,
          border: `1px solid ${uploadTokens.parsing.border}`,
          maxWidth: '85%',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography sx={{ fontSize: 14 }}>📄</Typography>
          <Typography variant="body2" sx={{ flex: 1 }}>
            {fileName}
          </Typography>
          <Typography
            sx={{
              fontSize: 14,
              animation: `${pulse} 1.5s ease-in-out infinite`,
            }}
          >
            🔄
          </Typography>
          <Typography variant="caption" sx={{ color: '#5D4037' }}>解读中</Typography>
        </Box>
      </Paper>
    );
  }

  if (status === 'completed') {
    return (
      <Paper
        elevation={0}
        sx={{
          mx: 2, my: 1,
          borderRadius: uploadTokens.radius,
          background: uploadTokens.completed.gradient,
          border: `1px solid ${uploadTokens.completed.border}`,
          maxWidth: '85%',
          overflow: 'hidden',
        }}
      >
        <Box
          sx={{
            p: 1.5, display: 'flex', alignItems: 'center', gap: 1,
            cursor: report ? 'pointer' : 'default',
            '&:hover': report ? { opacity: 0.9 } : {},
          }}
          onClick={() => report && setExpanded(!expanded)}
        >
          <Typography sx={{ fontSize: 14 }}>📄</Typography>
          <Typography variant="body2" sx={{ flex: 1 }}>
            {fileName}
          </Typography>
          <Typography sx={{ fontSize: 14 }}>✅</Typography>
          <Typography variant="caption" sx={{ color: '#2E7D32' }}>解析完成</Typography>
          {report && (
            <Typography variant="caption" sx={{ color: '#388E3C' }}>
              {expanded ? '收起 ▲' : '展开 ▼'}
            </Typography>
          )}
        </Box>
        {report && expanded && (
          <Box sx={{ px: 1, pb: 1 }}>
            <LabReportCard report={report} />
          </Box>
        )}
      </Paper>
    );
  }

  if (status === 'failed') {
    return (
      <Paper
        elevation={0}
        sx={{
          mx: 2, my: 1, p: 1.5,
          borderRadius: uploadTokens.radius,
          background: uploadTokens.failed.gradient,
          border: `1px solid ${uploadTokens.failed.border}`,
          maxWidth: '85%',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography sx={{ fontSize: 14 }}>📄</Typography>
          <Typography variant="body2" sx={{ flex: 1 }}>
            {fileName}
          </Typography>
          <Typography sx={{ fontSize: 14 }}>❌</Typography>
          <Typography variant="caption" sx={{ color: '#C62828' }}>解析失败</Typography>
        </Box>
        {error && (
          <Typography variant="caption" sx={{ color: '#8D6E63', mt: 0.5, display: 'block', ml: 3 }}>
            {error}
          </Typography>
        )}
      </Paper>
    );
  }

  return null;
}
