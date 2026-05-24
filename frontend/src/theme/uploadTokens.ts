export const uploadTokens = {
  parsing:    { gradient: 'linear-gradient(135deg, #FFF8E1, #FFF3E0)', border: '#FFE082' },
  completed:  { gradient: 'linear-gradient(135deg, #E8F5E9, #F1F8E9)', border: '#A5D6A7' },
  failed:     { gradient: 'linear-gradient(135deg, #FFF3E0, #FBE9E7)', border: '#FFAB91' },
  persistent: { gradient: 'linear-gradient(135deg, #FFEBEE, #FCE4EC)', border: '#EF9A9A' },
  idle:       { bg: '#F3F8FD', border: '#BBDEFB' },
  radius: 0,
} as const;
