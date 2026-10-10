// BC errors reach the Hub as JSON ('{"error":{"code":...,"message":"Item does
// not exist.  CorrelationId: ..."}}'). Staff see only BC's message, plus the
// item it was about when the Hub recorded it as "(FX60503B: {...".
export function plainBcError(text) {
  if (!text) return '';
  const t = String(text);
  const m = t.match(/"message"\s*:\s*"([^"]+)/);
  const code = t.match(/\(([A-Z0-9][A-Z0-9-]{3,})[):]/);
  if (m) return `${code ? 'item ' + code[1] + ': ' : ''}${m[1].replace(/\s*CorrelationId:.*$/i, '').trim()}`;
  return t.length > 160 ? t.slice(0, 160) + '…' : t;
}
