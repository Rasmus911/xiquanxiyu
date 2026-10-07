const path = require('node:path')
const { getTarget, normalizeReleaseTrust } = require('../electron/target-profiles.cjs')

function makeWindowsConfig({ projectRoot, version, buildId, targetId, trust }) {
  if (typeof projectRoot !== 'string' || !path.isAbsolute(projectRoot)) throw new TypeError('构建根目录必须为绝对路径')
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(String(version))) throw new TypeError('应用版本必须为x.y.z')
  if (typeof buildId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(buildId)) throw new TypeError('构建标识无效')
  const profile = getTarget(targetId)
  const releaseTrust = normalizeReleaseTrust(trust)
  const releaseRoot = path.join(projectRoot, 'release', 'windows', version, buildId)
  return {
    appId: 'com.xiquan.bathhouse',
    productName: '溪泉洗浴管理系统',
    electronVersion: profile.electronVersion,
    electronUpdaterCompatibility: '>=2.16.0',
    artifactName: `Xiquan-Bathhouse-Setup-\${version}-${targetId}.\${ext}`,
    directories: { output: path.join(releaseRoot, targetId) },
    files: ['dist/**/*', 'electron/**/*', '!electron/**/*.node-test.cjs', 'package.json'],
    extraMetadata: { version, xiquanDesktop: { schemaVersion: 1, ...profile, buildId, releaseTrust } },
    win: { target: [{ target: 'nsis', arch: [profile.arch] }] },
    nsis: {
      oneClick: false,
      allowToChangeInstallationDirectory: true,
      createDesktopShortcut: true,
      createStartMenuShortcut: true,
      shortcutName: '溪泉洗浴管理系统',
      deleteAppDataOnUninstall: false,
      include: path.join(releaseRoot, 'configs', `${targetId}.nsh`),
    },
    // builder merges a programmatic publish object into package.json's first provider.
    publish: { provider: 'generic', url: `https://api.pqxqxy.xyz/updates/desktop/${targetId}/`, channel: 'latest' },
  }
}

module.exports = { makeWindowsConfig }
