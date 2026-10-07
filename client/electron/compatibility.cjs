function windowBounds(workArea) {
  const width = Math.max(1, Math.floor(Number(workArea?.width) || 1024))
  const height = Math.max(1, Math.floor(Number(workArea?.height) || 700))
  return { width: Math.min(1440, width), height: Math.min(900, height),
    minWidth: Math.min(1024, width), minHeight: Math.min(700, height) }
}
function diagnostics({ profile, versions, osRelease, softwareRendering }) {
  return {
    targetId: String(profile?.targetId || 'development'), appArch: String(profile?.arch || process.arch),
    electronVersion: String(versions.electron || ''), chromiumVersion: String(versions.chrome || ''),
    nodeVersion: String(versions.node || ''), osRelease: String(osRelease || ''),
    buildId: String(profile?.buildId || 'development'), softwareRendering: softwareRendering === true,
    testOnly: profile?.releaseTrust?.testOnly === true,
  }
}
function readRenderingPreference(text) {
  try { return JSON.parse(text)?.softwareRendering === true } catch { return false }
}
module.exports = { windowBounds, diagnostics, readRenderingPreference }
