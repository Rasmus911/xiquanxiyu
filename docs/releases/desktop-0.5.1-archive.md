# 0.5.1 历史公开文件归档

归档只处理枚举的0.4.9、0.5.0桌面构建/交付副本、1.2.6–1.2.8旧手机包、五个确切旧源码包及0.1.0旧说明。当前0.5.1交付、1.2.9APK、线上deploy发布文件、运行时缓存、密钥、数据库、备份、.git、完整迁移链与共享旧名称脚本均保留。

分类目录为 archive/desktop/版本/目标、archive/mobile/版本、archive/source/版本、archive/documents/版本。每个分类内 desktop051-history.json 记录原路径、版本、大小、SHA256和有序分片。实际字节以SHA256去重保存在archive/objects，避免反复上传四包中相同的Electron文件。

普通Git单文件最多90MiB，超过拆成32MiB分片。恢复时按 manifest.pieces 的顺序逐字节连接，复核总size与sha256，不能把分片直接当安装包运行。原文件未完成远端字节验证不会删除。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\archive-desktop-051.ps1' -Mode prepare
```

然后通过桌面指定 GitHub Desktop.lnk 打开仓库 xiquanxiyu，核对只含 archive 分类内容，Commit、Push origin。不是本地提交就可以删除；必须推送到 https://github.com/Rasmus911/xiquanxiyu 的main分支。

历史文件总量较大时，先执行以下命令准备第一个不超过400MiB的上传批次，其余已验证副本临时保存在private/desktop051-archive/upload-queue。`.gitattributes`禁止objects自动转换换行，确保旧文件逐字节保真。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\archive-desktop-051.ps1' -Mode batch
```

每批通过GitHub Desktop Commit、Push完成后，再执行同一条batch命令准备下一批。它核对前一批已推送，不会偷偷CLI Push。输出finished:true后才执行verify、clean。不要把全部几GiB的原始包一次推送，也不要删除未推送队列。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\archive-desktop-051.ps1' -Mode verify
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\archive-desktop-051.ps1' -Mode clean
```

清理前重新读取远端commit及实际blob、核对分片和拼接后的原hash，同时检查本地文件未变化。证明有效期24小时。只删除精确叶文件，不递归删除目录；清理回执在 private/desktop051-archive/cleanup-receipt.json，包含每条恢复位置。任何认证、网络、哈希或新版本校验错误都会停止，原文件保留。

版本仓库不是运行洗浴系统必需，但它是当前归档和远端证明所需工具，未完成归档前不能删。发布密钥必须保存才能给旧客户端提供可信更新；私有保留中的配置、备份证据同样不能因清理而删除。
