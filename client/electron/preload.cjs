const { contextBridge, ipcRenderer } = require('electron')

// Sandboxed preload scripts can only require a small set of Electron/Node
// built-ins. Keep this conversion here so a packaged window can expose the
// desktop bridge instead of failing while loading a local CommonJS module.
function toTerminalConfig(value) {
  const source = value && typeof value === 'object' ? value : {}
  return {
    serverUrl: String(source.serverUrl || ''),
    terminalCode: String(source.terminalCode || ''),
    terminalName: String(source.terminalName || ''),
    printerName: String(source.printerName || ''),
  }
}

contextBridge.exposeInMainWorld('xiquan', {
  getConfig: () => ipcRenderer.invoke('config:get'),
  getDesktopDiagnostics: () => ipcRenderer.invoke('desktop:diagnostics'),
  restartWithSoftwareRendering: enabled => ipcRenderer.invoke('desktop:software-rendering', enabled === true),
  setConfig: (config) => ipcRenderer.invoke('config:set', toTerminalConfig(config)),
  getPrinters: () => ipcRenderer.invoke('printer:list'),
  printReceipt: (receipt, printerName) => ipcRenderer.invoke('printer:receipt', receipt, printerName),
  getUpdateState: () => ipcRenderer.invoke('updater:get-state'),
  checkForUpdates: () => ipcRenderer.invoke('updater:check'),
  installUpdate: () => ipcRenderer.invoke('updater:install'),
  setBusinessBusy: (reason) => ipcRenderer.invoke(
    'updater:set-business-busy',
    typeof reason === 'string' ? reason : null,
  ),
  onUpdateState: (listener) => {
    const handler = (_event, state) => listener(state)
    ipcRenderer.on('updater:state', handler)
    return () => ipcRenderer.removeListener('updater:state', handler)
  },
})
