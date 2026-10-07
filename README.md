# 溪泉洗浴管理系统

当前归档源码版本：桌面 **0.4.8**，安卓 **1.2.6**。网页、桌面和手机共用云端 API；本仓库不包含生产数据库或任何签名私钥。

## 文件分类

- 仓库根目录：当前版本经过凭据检查的源码、数据库迁移、测试与发布脚本。
- `archive/desktop/<版本>/`：历史源码快照 ZIP 和该版本 SHA256 清单。
- `archive/versions.json`：历史桌面安装包、安卓安装包的版本、大小和 SHA256 总目录。
- [GitHub Releases](https://github.com/Rasmus911/xiquanxiyu/releases)：大型桌面 EXE 与安卓 APK，按版本分类，不放入普通 Git 文件历史。

## 开发结构

- `client/`：Vue 3、Element Plus 和 Electron 桌面端。
- `mobile/`：Vue 3 和 Capacitor 安卓端。
- `server/`：Flask API、数据库模型及 Alembic 迁移。
- `deploy/cloud/`：Docker、Nginx 和云端部署脚本模板。
- `scripts/`：构建、签名、发布与验收工具。
- `docs/releases/`：版本交付说明。

旧版本编号的迁移和辅助脚本仍可能是最新版依赖，不能仅因文件名包含旧版本就删除。

## 归档边界

历史快照来自本地明确的 Git 提交，并以 `manifest.json` 记录原始提交号；不把原始私有 Git 对象历史直接公开。
0.1.0、0.2.3、0.4.0 只有已找到的历史二进制，未确认与其完全匹配的源码，因此不冒充对应源码版本。

证书、密码、`.env`、会员/交易数据库、备份、真实库存照片数据与失败构建证据留在本机私有归档，不上传公开仓库。
旧安装包仅用于归档与回溯；新部署应使用最新交付说明、原签名证书和已校验的安装包。
