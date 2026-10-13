# 0.5.0 版本归档与精确清理

保留当前源码、完整数据库迁移链、共享脚本、`.git`、`private` 中原签名密钥与恢复证据、当前运行时缓存、桌面0.5.0交付、安卓1.2.9。历史迁移/旧部署基类仍被最新版使用，不因名字旧而删除。

归档仓库沿用 `F:\溪泉洗浴系统\private\溪泉版本仓库\xiquanxiyu`，远端必须是 https://github.com/Rasmus911/xiquanxiyu 。不创建第二个公开仓库。

```powershell
# 只读列出确切旧文件；不清理。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\archive-desktop-050.ps1' -Mode plan

# 先重新核实线上 main。未归档的小文件经保密检查后复制到原归档仓库。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\archive-desktop-050.ps1' -Mode prepare
```

GitHub Desktop 选择 `xiquanxiyu`，确认 Repository → Repository settings 的远端为指定地址，检查 Changes 中没有私钥、`.env`、数据库或会员资料。填写提交说明“归档0.4.9与安卓1.2.8剩余交付文件”，Commit to main，然后 **Push origin**。本地提交不等于上传成功。

新的普通Git文件限制90MiB。现有大桌面安装包沿用已经上传的32MiB分片，核实每个分片及合并后的完整SHA256，不重新提交100MiB以上EXE。后续新增大文件应上传对应GitHub Release资产，不通过调高限制强行Push。

```powershell
# 必须已经构建四个0.5.0安装包；每次都重新读远端提交及内容，不信任旧证明。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'F:\溪泉洗浴系统\scripts\archive-desktop-050.ps1' -Mode clean
```

clean 逐文件核实绝对路径、非链接、版本、大小、SHA256、指定远端及24小时内证明，再仅删除已核实单个旧文件。空的旧交付目录非递归删除。无对应远端字节证明的旧解包中间文件保留，不能用“有个相似安装包”作为清理依据。未能控制GitHub Desktop时需用户完成Push，不会换成未经要求的git push。

清理报告位于 `private\desktop050-archive`，包含远端提交和可恢复文件清单。没有真实上传/核实记录前，不宣称项目已经完全清理。
