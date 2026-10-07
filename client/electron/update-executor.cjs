function createPinnedExecutorClass(Base) {
  return class PinnedExecutor extends Base {
    constructor({ origin, feedPath }) {
      super()
      const source = new URL(origin)
      if (source.protocol !== 'https:' || source.username || source.password ||
          !/^\/updates\/desktop\/(win7|win10|win11)-(x86|x64)\/$/.test(feedPath)) {
        throw new TypeError('更新下载来源无效')
      }
      this.allowedOrigin = source.origin
      this.allowedFeedPath = feedPath
      this.maxRedirects = 0
    }
    createRequest(options, callback) {
      let url
      try {
        if (options.auth || options.protocol !== 'https:' || typeof options.path !== 'string' ||
            !options.path.startsWith(this.allowedFeedPath) || /[%\\]/.test(options.path.split('?')[0])) throw new Error()
        url = new URL(options.path, `${options.protocol}//${options.hostname}${options.port ? `:${options.port}` : ''}`)
        if (url.origin !== this.allowedOrigin || url.username || url.password || url.hash ||
            !url.pathname.startsWith(this.allowedFeedPath) || url.pathname.slice(this.allowedFeedPath.length).includes('/')) throw new Error()
      } catch { throw new TypeError('更新下载来源或目标目录不匹配') }
      let request
      request = super.createRequest(options, response => {
        if (response.statusCode >= 300 && response.statusCode < 400) {
          response.resume()
          request.emit('error', new Error('更新下载不允许重定向'))
          request.abort()
          return
        }
        callback(response)
      })
      return request
    }
    addRedirectHandlers(request, _options, reject) {
      request.on('redirect', () => {
        request.abort()
        reject(new Error('更新下载不允许重定向'))
      })
    }
    handleResponse(response, options, token, resolve, reject, ...rest) {
      if (response.statusCode >= 300 && response.statusCode < 400) {
        response.resume()
        reject(new Error('更新下载不允许重定向'))
        return
      }
      return super.handleResponse(response, options, token, resolve, reject, ...rest)
    }
  }
}

module.exports = { createPinnedExecutorClass }
