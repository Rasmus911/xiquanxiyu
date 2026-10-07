function toTerminalConfig(value) {
  const source = value && typeof value === 'object' ? value : {}
  return {
    serverUrl: String(source.serverUrl || ''),
    terminalCode: String(source.terminalCode || ''),
    terminalName: String(source.terminalName || ''),
    printerName: String(source.printerName || ''),
  }
}

function toPrinterInfo(value) {
  const source = value && typeof value === 'object' ? value : {}
  return {
    name: String(source.name || ''),
    displayName: String(source.displayName || source.name || ''),
    description: String(source.description || ''),
    status: Number(source.status || 0),
    isDefault: Boolean(source.isDefault),
  }
}

function toPrinterList(values) {
  if (!Array.isArray(values)) return []
  return values
    .map(toPrinterInfo)
    .filter((printer) => printer.name)
    .sort((left, right) => Number(right.isDefault) - Number(left.isDefault) || left.name.localeCompare(right.name))
}

module.exports = { toPrinterInfo, toPrinterList, toTerminalConfig }
