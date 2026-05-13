import { Box, Typography, Chip, IconButton, Fade, Stack, Divider } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import LocalHospitalIcon from '@mui/icons-material/LocalHospital';
import ScienceIcon from '@mui/icons-material/Science';
import MedicationIcon from '@mui/icons-material/Medication';
import type { DiagnosisReport } from '../types/agent';

interface Props {
  report: DiagnosisReport;
  visible: boolean;
  onClose: () => void;
}

function ConfidenceStars({ level }: { level: string }) {
  const count = level === 'high' ? 5 : level === 'medium' ? 3 : 1;
  return (
    <Box component="span" sx={{ color: '#FFB300', fontSize: 14 }}>
      {'⭐'.repeat(count)}{'☆'.repeat(5 - count)}
    </Box>
  );
}

function Section({ icon, title, children }: { icon: string; title: string; children: React.ReactNode }) {
  return (
    <Box sx={{ mb: 2.5 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'text.primary', display: 'flex', alignItems: 'center', gap: 0.8 }}>
        <Box component="span" sx={{ fontSize: '1.1rem' }}>{icon}</Box>
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function DiffItem({ diagnosis, icd11_code, reasoning }: { diagnosis: string; icd11_code?: string; reasoning?: string }) {
  return (
    <Box sx={{ mb: 1.5, pl: 1, borderLeft: '2px solid', borderColor: 'divider' }}>
      <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.3 }}>
        {diagnosis}
        {icd11_code ? (
          <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
            ICD-11: {icd11_code}
          </Typography>
        ) : null}
      </Typography>
      {reasoning && (
        <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.85rem', lineHeight: 1.5 }}>
          {reasoning}
        </Typography>
      )}
    </Box>
  );
}

export default function FullScreenReport({ report, visible, onClose }: Props) {
  if (!visible) return null;

  return (
    <Fade in={visible} timeout={400}>
      <Box
        sx={{
          position: 'fixed',
          inset: 0,
          zIndex: 1300,
          bgcolor: '#FAFAFA',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Header */}
        <Box
          sx={{
            position: 'sticky',
            top: 0,
            zIndex: 10,
            bgcolor: 'background.paper',
            borderBottom: '1px solid',
            borderColor: 'divider',
            px: 2,
            py: 1.5,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <IconButton onClick={onClose} size="small" sx={{ color: 'text.secondary' }}>
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, color: 'primary.main', display: 'flex', alignItems: 'center', gap: 1 }}>
            <LocalHospitalIcon fontSize="small" />
            诊断报告
          </Typography>
          <IconButton onClick={onClose} size="small" sx={{ color: 'text.secondary' }}>
            <CloseIcon />
          </IconButton>
        </Box>

        {/* Body */}
        <Box sx={{ flex: 1, px: 2.5, py: 2, maxWidth: 720, mx: 'auto', width: '100%' }}>
          {/* Primary Diagnosis */}
          <Section icon="🏥" title="初步诊断">
            <Typography variant="h5" sx={{ fontWeight: 700, color: 'primary.main', mb: 0.5 }}>
              {report.primary_diagnosis}
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 1, flexWrap: 'wrap' }}>
              <Typography variant="body2" color="text.secondary">置信度:</Typography>
              <ConfidenceStars level={report.confidence} />
              <Chip
                label={report.confidence === 'high' ? '高' : report.confidence === 'medium' ? '中' : '低'}
                size="small"
                color={report.confidence === 'high' ? 'success' : report.confidence === 'medium' ? 'warning' : 'error'}
                sx={{ height: 22, fontSize: 12 }}
              />
              {report.severity && (
                <Chip
                  label={report.severity === 'mild' ? '轻度' : report.severity === 'moderate' ? '中度' : report.severity === 'severe' ? '重度' : report.severity}
                  size="small"
                  variant="outlined"
                  sx={{ height: 22, fontSize: 12 }}
                />
              )}
            </Box>
          </Section>

          <Divider sx={{ my: 2 }} />

          {/* Differential */}
          {report.differential_diagnoses && report.differential_diagnoses.length > 0 && (
            <>
              <Section icon="🔍" title="鉴别诊断">
                <Stack spacing={0.5}>
                  {report.differential_diagnoses.map((d, i) => (
                    <DiffItem key={i} diagnosis={d.diagnosis} icd11_code={d.icd11_code} reasoning={d.reasoning} />
                  ))}
                </Stack>
              </Section>
              <Divider sx={{ my: 2 }} />
            </>
          )}

          {/* Key Findings */}
          {report.key_findings && report.key_findings.length > 0 && (
            <>
              <Section icon="📋" title="关键发现">
                <Stack spacing={0.8}>
                  {report.key_findings.map((f, i) => (
                    <Typography key={i} variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                      • {f}
                    </Typography>
                  ))}
                </Stack>
              </Section>
              <Divider sx={{ my: 2 }} />
            </>
          )}

          {/* Recommended Tests */}
          {report.recommended_tests && report.recommended_tests.length > 0 && (
            <>
              <Section icon="🧪" title="推荐检查">
                <Stack spacing={0.8}>
                  {report.recommended_tests.map((t, i) => (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
                      <ScienceIcon sx={{ fontSize: 16, color: 'primary.light', mt: 0.3 }} />
                      <Typography variant="body2" color="text.secondary">{t}</Typography>
                    </Box>
                  ))}
                </Stack>
              </Section>
              <Divider sx={{ my: 2 }} />
            </>
          )}

          {/* Actions */}
          {report.recommended_actions && report.recommended_actions.length > 0 && (
            <>
              <Section icon="💊" title="建议措施">
                <Stack spacing={0.8}>
                  {report.recommended_actions.map((a, i) => (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
                      <MedicationIcon sx={{ fontSize: 16, color: 'primary.light', mt: 0.3 }} />
                      <Typography variant="body2" color="text.secondary">{a}</Typography>
                    </Box>
                  ))}
                </Stack>
              </Section>
              <Divider sx={{ my: 2 }} />
            </>
          )}

          {/* Red Flags */}
          {report.red_flags && report.red_flags.length > 0 && (
            <Section icon="🚨" title="危险信号（需立即就医）">
              <Box sx={{ bgcolor: '#FFF3E0', borderRadius: 2, p: 2, border: '1px solid #FFB74D' }}>
                <Stack spacing={0.8}>
                  {report.red_flags.map((r, i) => (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
                      <WarningAmberIcon sx={{ fontSize: 16, color: '#E65100', mt: 0.3 }} />
                      <Typography variant="body2" sx={{ color: '#E65100', fontWeight: 500 }}>{r}</Typography>
                    </Box>
                  ))}
                </Stack>
              </Box>
            </Section>
          )}

          {/* Disclaimer */}
          <Box sx={{ mt: 3, pt: 2, borderTop: '1px solid', borderColor: 'divider' }}>
            <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.6 }}>
              {report.disclaimer || '本报告由 AI 生成，仅供参考，不能替代专业医疗诊断。患者应尽快就医，由医生进行全面评估和确诊。'}
            </Typography>
          </Box>
        </Box>
      </Box>
    </Fade>
  );
}
