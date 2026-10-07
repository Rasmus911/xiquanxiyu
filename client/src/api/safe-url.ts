export function safeApiUrl(value: string) {
  const url = new URL(value)
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  if (!(url.protocol === 'https:' || (url.protocol === 'http:' && loopback))
    || url.username || url.password || url.search || url.hash || !/^\/api\/?$/.test(url.pathname)) {
    throw new Error('服务器地址必须是 HTTPS /api 地址；仅本机开发允许 http://127.0.0.1:端口/api')
  }
  return value.replace(/\/$/, '')
}
