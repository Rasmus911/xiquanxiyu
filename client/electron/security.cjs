function isTrustedPage(actual, expected) {
  try {
    const url = new URL(actual)
    const allowed = new URL(expected)
    return url.protocol === allowed.protocol && url.origin === allowed.origin && url.pathname === allowed.pathname && url.search === allowed.search
  } catch { return false }
}

function isTrustedIpc(event, senderId, expected) {
  return event.sender?.id === senderId && event.senderFrame && !event.senderFrame.parent && isTrustedPage(event.senderFrame.url, expected)
}

function menuTemplate(development) {
  return [
    { label: '文件', submenu: [{ label: '关闭窗口', role: 'close' }] },
    { label: '编辑', submenu: [
      { label: '撤销', role: 'undo', accelerator: 'CommandOrControl+Z' },
      { label: '重做', role: 'redo', accelerator: 'CommandOrControl+Y' },
      { type: 'separator' },
      { label: '剪切', role: 'cut', accelerator: 'CommandOrControl+X' },
      { label: '复制', role: 'copy', accelerator: 'CommandOrControl+C' },
      { label: '粘贴', role: 'paste', accelerator: 'CommandOrControl+V' },
      { label: '全选', role: 'selectAll', accelerator: 'CommandOrControl+A' },
    ] },
    { label: '显示', submenu: [
      { label: '恢复缩放', role: 'resetZoom' },
      { label: '放大', role: 'zoomIn' },
      { label: '缩小', role: 'zoomOut' },
      ...(development ? [{ role: 'reload' }, { role: 'toggleDevTools' }] : []),
    ] },
  ]
}

module.exports = { isTrustedPage, isTrustedIpc, menuTemplate }
