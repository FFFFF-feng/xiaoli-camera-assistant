// HTTP is intentionally restricted to a trusted LAN demo, not public deployment.
export function normalizeBaseUrl(value) {
  const url = new URL(value.trim());
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('请填写服务根地址，例如 http://192.168.1.20:8000，不要带路径或账号。');
  }
  const host = url.hostname;
  const parts = host.split('.').map(Number);
  const ipv4 = parts.length === 4 && parts.every((part) => Number.isInteger(part) && part >= 0 && part <= 255);
  const privateHost = host === 'localhost' || (ipv4 && (
    parts[0] === 127 || parts[0] === 10 ||
    (parts[0] === 192 && parts[1] === 168) ||
    (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31)
  ));
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && privateHost)) {
    throw new Error('公网服务必须使用 HTTPS；HTTP 仅用于可信局域网演示。');
  }
  return url.origin;
}

export function safeSourceUrl(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}
