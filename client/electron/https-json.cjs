const https = require('node:https')

function requestHttpsBuffer(input, { allowedOrigin, maxBytes = 512 * 1024, timeoutMs = 10000, request = https.request } = {}) {
  return new Promise((resolve, reject) => {
    let url
    try {
      url = new URL(String(input))
      const allowed = new URL(allowedOrigin)
      if (url.protocol !== 'https:' || allowed.protocol !== 'https:' || url.username || url.password ||
          allowed.username || allowed.password || url.hash || url.origin !== allowed.origin ||
          !Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 8 * 1024 * 1024 ||
          !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000) throw new Error()
    } catch {
      reject(new TypeError('更新请求必须使用可信HTTPS地址和有效限制'))
      return
    }
    let req
    let response
    let settled = false
    let timer
    function fail(error) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      response?.destroy()
      req?.destroy()
      reject(error)
    }
    function networkFailure() { fail(new Error('更新网络请求失败，请检查连接与证书')) }
    timer = setTimeout(() => fail(new Error('更新请求超时')), timeoutMs)
    try {
      req = request(url, {
        method: 'GET', rejectUnauthorized: true,
        headers: { Accept: 'application/json, application/octet-stream', 'Cache-Control': 'no-cache' },
      }, incoming => {
        response = incoming
        if (settled) { incoming.destroy(); return }
        if (incoming.statusCode !== 200) {
          incoming.resume()
          fail(new Error(`更新请求失败（HTTP ${Number(incoming.statusCode) || 0}）`))
          return
        }
        let size = 0
        let ended = false
        const chunks = []
        incoming.on('data', chunk => {
          if (settled) return
          const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
          size += bytes.length
          if (size > maxBytes) { fail(new Error('更新响应超过大小限制')); return }
          chunks.push(bytes)
        })
        incoming.once('aborted', () => fail(new Error('更新响应不完整')))
        incoming.once('error', networkFailure)
        incoming.once('close', () => { if (!ended && !settled) fail(new Error('更新响应不完整')) })
        incoming.once('end', () => {
          ended = true
          if (settled) return
          settled = true
          clearTimeout(timer)
          resolve(Buffer.concat(chunks))
        })
      })
      req.once('error', networkFailure)
      if (settled) req.destroy()
      else req.end()
    } catch { networkFailure() }
  })
}

async function requestHttpsJson(url, options) {
  const body = await requestHttpsBuffer(url, options)
  try { return JSON.parse(body.toString('utf8').replace(/^\uFEFF/, '')) }
  catch { throw new Error('更新响应格式无效') }
}

module.exports = { requestHttpsBuffer, requestHttpsJson }
