import { useState } from 'react';
import { Box, Typography, Chip, TextField, Button, Paper, Fade } from '@mui/material';
import MedicalInformationIcon from '@mui/icons-material/MedicalInformation';
import type { InterviewQuestion } from '../types/agent';

interface Props {
  question: InterviewQuestion;
  onAnswer: (questionId: string, answer: string) => void;
  disabled?: boolean;
}

/**
 * Phase color mapping for visual feedback
 */
const PHASE_COLORS: Record<string, { bg: string; border: string; icon: string }> = {
  '症状情况': { bg: '#FFF3E0', border: '#FFB74D', icon: '🌡️' },
  '就诊情况': { bg: '#E3F2FD', border: '#64B5F6', icon: '🏥' },
  '健康状况': { bg: '#E8F5E9', border: '#81C784', icon: '💚' },
  '过敏情况': { bg: '#FCE4EC', border: '#F06292', icon: '⚠️' },
  '生活习惯': { bg: '#F3E5F5', border: '#BA68C8', icon: '🍺' },
  '工作生活': { bg: '#E0F7FA', border: '#4DD0E1', icon: '💼' },
  '出行情况': { bg: '#E8EAF6', border: '#7986CB', icon: '✈️' },
  '家人健康': { bg: '#FFF8E1', border: '#FFD54F', icon: '👨‍👩‍👧' },
  '用药情况': { bg: '#E0F2F1', border: '#4DB6AC', icon: '💊' },
  '补充': { bg: '#F5F5F5', border: '#BDBDBD', icon: '📝' },
};

function getPhaseStyle(phase?: string) {
  if (!phase) return { bg: '#FFF8F0', border: '#F5E6D3', icon: '💬' };
  return PHASE_COLORS[phase] || { bg: '#FFF8F0', border: '#F5E6D3', icon: '💬' };
}

export default function InterviewQuestion({ question, onAnswer, disabled = false }: Props) {
  const [textAnswer, setTextAnswer] = useState('');
  const [answered, setAnswered] = useState(false);

  const phaseStyle = getPhaseStyle(question.colloquial_phase);

  const handleChoice = (option: string) => {
    if (disabled || answered) return;
    setAnswered(true);
    onAnswer(question.question_id, option);
  };

  const handleTextSubmit = () => {
    const trimmed = textAnswer.trim();
    if (!trimmed || disabled || answered) return;
    setAnswered(true);
    onAnswer(question.question_id, trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleTextSubmit();
    }
  };

  return (
    <Fade in={true} timeout={400}>
      <Paper
        elevation={0}
        sx={{
          mt: 1.5,
          mb: 1,
          p: 2,
          borderRadius: 3,
          bgcolor: phaseStyle.bg,
          border: `2px solid ${phaseStyle.border}`,
          transition: 'all 0.3s ease',
        }}
      >
        {/* Phase indicator */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 1 }}>
          <Typography variant="caption" sx={{ fontSize: '1rem' }}>
            {phaseStyle.icon}
          </Typography>
          <Typography
            variant="caption"
            sx={{
              fontWeight: 600,
              color: '#5C4033',
              textTransform: 'uppercase',
              letterSpacing: 0.5,
            }}
          >
            {question.colloquial_phase || '问诊'}
          </Typography>
          <Box sx={{ flex: 1 }} />
          <MedicalInformationIcon sx={{ fontSize: 16, color: phaseStyle.border }} />
        </Box>

        <Typography variant="subtitle2" sx={{ fontWeight: 600, color: '#3E2723', mb: 1.5, lineHeight: 1.5, wordBreak: 'break-word', overflowWrap: 'break-word', fontSize: '0.95rem' }}>
          {question.question}
        </Typography>

        {question.hint && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5, fontStyle: 'italic' }}>
            💡 {question.hint}
          </Typography>
        )}

        {question.type === 'choice' && question.options && (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
            {question.options.map((option) => (
              <Chip
                key={option}
                label={option}
                clickable
                disabled={disabled || answered}
                onClick={() => handleChoice(option)}
                sx={{
                  bgcolor: answered ? phaseStyle.bg : '#FFFFFF',
                  border: `1.5px solid ${phaseStyle.border}`,
                  color: '#3E2723',
                  fontWeight: 500,
                  fontSize: 14,
                  px: 0.5,
                  '&:hover': {
                    bgcolor: phaseStyle.bg,
                    borderColor: phaseStyle.border,
                    transform: 'translateY(-1px)',
                  },
                  '&.Mui-disabled': {
                    opacity: answered ? 0.7 : 0.4,
                    bgcolor: '#FFFFFF',
                  },
                  transition: 'all 0.2s ease',
                }}
              />
            ))}
            {question.allow_skip && (
              <Chip
                label="跳过这题"
                clickable
                disabled={disabled || answered}
                onClick={() => handleChoice('skipped')}
                sx={{
                  bgcolor: 'transparent',
                  border: `1.5px dashed ${phaseStyle.border}`,
                  color: '#8B7355',
                  fontSize: 13,
                  '&:hover': {
                    bgcolor: phaseStyle.bg,
                    borderColor: phaseStyle.border,
                  },
                }}
              />
            )}
          </Box>
        )}

        {question.type === 'text' && (
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-end' }}>
            <TextField
              fullWidth
              size="small"
              placeholder="请输入您的回答..."
              value={textAnswer}
              onChange={(e) => setTextAnswer(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled || answered}
              variant="outlined"
              sx={{
                '& .MuiOutlinedInput-root': {
                  bgcolor: '#FFFFFF',
                  borderRadius: 2,
                  fontSize: 14,
                  '& fieldset': {
                    borderColor: phaseStyle.border,
                  },
                  '&:hover fieldset': {
                    borderColor: phaseStyle.border,
                  },
                  '&.Mui-focused fieldset': {
                    borderColor: phaseStyle.border,
                    borderWidth: 2,
                  },
                },
              }}
            />
            <Button
              variant="contained"
              size="small"
              onClick={handleTextSubmit}
              disabled={disabled || answered || !textAnswer.trim()}
              sx={{
                minWidth: 64,
                borderRadius: 2,
                bgcolor: phaseStyle.border,
                '&:hover': { bgcolor: phaseStyle.border, opacity: 0.9 },
                '&.Mui-disabled': { bgcolor: '#F5E6D3', color: '#8B7355' },
                textTransform: 'none',
                fontWeight: 600,
              }}
            >
              回答
            </Button>
          </Box>
        )}

        {answered && (
          <Typography variant="caption" color="success.main" sx={{ mt: 1, display: 'block', fontWeight: 500 }}>
            ✅ 已记录您的回答
          </Typography>
        )}
      </Paper>
    </Fade>
  );
}
