# 0.4.9 构建核验与发布边界

公开桌面更新说明：新增 账号注册功能

本文先于最终构建提交。最终构建必须使用包含本文的未变更 HEAD；构建后不再提交源码来改变产物的 SourceCommit。确切源码提交、SOURCE/WEB ZIP 名称与 SHA256 记录在生成的 `交付信息.json` 和 ZIP 内 `source-manifest.json`；四目标实际版本、PE 架构、原公开信任、安装包/更新元数据哈希记录在构建目录 `delivery-index.json`。构建后的实际命令、结果、哈希、公开归档准备与保留清单另存本地工作报告，不把未执行事项写作成功。

## 已核验的公开前置条件

从原路径复制公开 Ed25519 公钥至 `release/trust/release-public-key.pem`，原件保留。原件与副本 SHA256 均为 `35a0ffde230c5e81dcec63845a063e61027ada146677629251a723a7c1447bba`，keyId 为 `b26477a9ed540ad0`；未创建新信任根、未读取私钥。

从 `release/runtime-cache/stock-20261005` 复制两个现代 Electron ZIP 至 `release/runtime-cache/current-windows`，原件保留，实际字节数与源码固定官方哈希匹配：

| 运行时 | 字节数 | SHA256 |
| --- | ---: | --- |
| electron-v43.7.7-win32-ia32.zip | 131079750 | a170eeedf4a216b3b0672b151294e7aef0b4fdc15ae5c207ea3f9f37c4a14c42 |
| electron-v44.5.1-win32-x64.zip | 157998329 | 9b382492dcfee91f8f9e92c91f7972550a1b95d2299cac72279dab33a600d7db |

同时保留并复制输入元数据 `windows-inputs-before.json` 和 `windows-inputs-after.json`，二者 SHA256 均为 `142500b8ae24af311ab35302bba584c43d987c70e178059082541ce993cb6f6f`。这些历史输入元数据不是当前 0.4.9 构建凭据。

实际 Windows PowerShell 子进程预检命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build-desktop-049.ps1 -BuildId 'registration049-preflight-20261008' -DryRun
```

预检退出码 0，版本 0.4.9，目标仅 `win10-x86`、`win10-x64`、`win11-x86`、`win11-x64`，现代 Electron 43.7.7 / 44.5.1、原信任 keyId、目标独立更新通道均匹配，`CloudChanged=false`、`UpdateSignature=pending-original-key`。此结果仅证明公开配置预检；最终四个安装包、完整 ZIP 回读、asar 源码身份和 StageOnly 必须在构建后再核验。

## 最终构建及本地核验

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\build-desktop-049.ps1' -BuildId 'registration049-delivery-20261008'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\最新版安装包-账号注册-0.4.9\01-部署云端.ps1' -StageOnly
Get-ChildItem -LiteralPath 'F:\溪泉洗浴系统\最新版安装包-账号注册-0.4.9' -File | Where-Object { $_.Extension -in @('.exe', '.apk', '.zip') } | Get-FileHash -Algorithm SHA256
```

核验完整四目标的实际 PE 架构、asar 内 package/version/target/trust、渲染页的注册入口及提交 buildId、renderer 文件与 SOURCE/WEB ZIP 的逐字节对应，ZIP 内 manifest 每个文件的大小/SHA256，以及 HEAD 与构建前一致。不得以 DryRun 或文件存在替代实际打包核验。不重新运行旧后端全套；功能和有界回归结果由本任务前序工作报告提供。

## 实际发布状态边界

本地构建不等于正式签名、在线更新发布、云端部署、隔离 PG17 恢复演练或真实设备覆盖安装。桌面更新仍需原 Ed25519 私钥的签名入口；没有 Authenticode 签名的 EXE 不称为已签名安装包。Android 1.2.7 / versionCode 14 / minimumVersionCode 9 / com.xiquan.mobileordering 正式 APK 等待人在本机隐藏密码提示下使用原签名证书构建；不能放入未签名测试 APK 充当正式版本。

部署、桌面原信任签名发布、Android 原证书 build/publish、失败恢复的完整命令与边界见 `2026-10-08-desktop-049.md`。员工从原 APP 应用内下载并覆盖安装。桌面旧版只有目标身份和原信任已核验时使用原通道，否则用对应目标原签名安装包覆盖安装；没有全历史二进制实机兼容证明。

公开源码只准备经 allowlist 与凭据扫描的当前快照和按版本清单，独立公共仓库由整体评审后使用 GitHub Desktop Commit/Push。私有主仓库历史、环境、证书/私钥、数据库备份和业务数据不得进入公共仓库。历史 0.4.3 Release 已有核验记录；其他完整历史二进制仍待逐项远端文件名/大小/SHA256 核验。仅在对应 GitHub 原件核验成功后才可执行明确目标的可恢复移动；本次构建工作人员不上传、不移动、不删除旧原件。
