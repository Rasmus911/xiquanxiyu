export function safeApiUrl(value: string) {
  const url = new URL(value)
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  if (!(url.protocol === 'https:' || (url.protocol === 'http:' && loopback))
    || url.username || url.password || url.search || url.hash || !/^\/api\/?$/.test(url.pathname)) {
    throw new Error('服务器地址必须使用 HTTPS，不能通过公网明文 HTTP 发送密码和账单')
  }
  return value.replace(/\/$/, '')
}
