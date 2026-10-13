# 照片库存盘点：人工核对、预览和提交

本说明只涉及照片盘点。CSV 是实际剩余库存的**目标余额**：既有 50 袋、照片 4 箱、每箱 200 袋，最终为 800 袋，流水调整 750 袋。原有未映射库存不会被清空，照片采购价格不会进入销售目录。此代码尚未代表云端已经迁移或导入；先完成人工部署流程中的备份、恢复验证及结构迁移验收，再由有库存写权限的员工执行。

已核对文件 `2026-10-05-photo-stock-review.csv` 保留 43 个不同来源行；22—24 行重叠只记录一次。目前 16 行 `ready`，27 行 `needs_*` 排除。排除行及其原始字段会显示在预览、回执和审计中。不要为使导入通过而把未确认状态改成 `ready`；新增确定事实须保留原文件并另存新核对版本，重新审核。奶膏/搓盐/搓泥按用户确认的袋计数，毛巾按条、刮胡泡按支、桶装品按桶。

## 1. 确认稳定库存 ID 或明确新建

要求 Python 3.9 或更高版本；脚本仅使用标准库，连接受保护 HTTP API，不直接连接数据库。使用正常交互式 PowerShell，不启用 transcript、命令调试或请求抓包。密码只在隐藏提示中输入；不存在密码或 token 命令行参数，不写入输出 JSON。使用已注册、启用的桌面终端代码；脚本不会注册或提升终端、账号权限。收银员/库管升级后须重新登录以取得五模块权限，本工具每次使用正常登录。

```powershell
Set-Location 'F:\溪泉洗浴系统'
$env:PYTHONUTF8 = '1'
$stockPython = '.\server\.venv\Scripts\python.exe'
$api = 'https://你的业务域名/api'  # 替换为现有业务域名，不能附带token
$operator = Read-Host '有库存权限的用户名'
$terminal = Read-Host '已注册桌面终端代码'
& $stockPython .\scripts\stock_import.py --api-url $api --username $operator --terminal-code $terminal list --output .\stock-ids-reviewed.json
```

人工阅读 `stock-ids-reviewed.json` 中的名称、稳定 `id`、基本单位、包装单位、箱规、当前余额和版本。脚本不按名称猜测或自动匹配。

保存一个 UTF-8 JSON 映射文件，例如 `stock-photo-mapping.json`。键为 CSV 原始行号字符串；已有主档用真实稳定 ID：`"1": {"stock_item_id": "这里替换为实际UUID"}`。基本单位、包装单位和换算系数须与照片行一致；不一致先核对实物和单位，不能把“原销售单位”的旧主档猜成袋。名称可以不同，但必须人工确认同一实物。一个主档不能被多个照片行覆盖。

只有在确认对应实物应新建独立主档时才用 `{"create": true}`。下面列出 16 个待人工逐行选择的键；**仅在逐一确认全为新项目后**才能直接采用此全新建示例，否则将相应行替换为已确认 ID：

```json
{
  "1": {"create": true}, "2": {"create": true}, "3": {"create": true},
  "5": {"create": true}, "7": {"create": true}, "9": {"create": true},
  "10": {"create": true}, "19": {"create": true}, "20": {"create": true},
  "21": {"create": true}, "25": {"create": true}, "36": {"create": true},
  "38": {"create": true}, "39": {"create": true}, "41": {"create": true},
  "43": {"create": true}
}
```

## 2. 非修改性预览

```powershell
& $stockPython .\scripts\stock_import.py --api-url $api --username $operator --terminal-code $terminal preview --csv .\docs\inventory\2026-10-05-photo-stock-review.csv --mapping .\stock-photo-mapping.json --output .\stock-photo-preview.json
```

逐行核对 `evidence` 原始照片行/规格/数量/单位、`input_quantity`/`input_unit`、`base_unit`、`target_quantity`、`before` 的当前主档及版本、`delta` 差额、`mapping` 和 `excluded`。第一行应显示输入 4.000 箱、目标 800.000 袋；第 10 行是原有 400 袋，不再乘 400；第 25 行是 12 支，不乘 72；第 39 行是 800 条，不乘 3000。不能把不同基本单位的目标数量相加作为总库存。

`source_sha256` 对原始 UTF-8 文件字节计算，包含 BOM 和换行差异。`preview_digest` 绑定来源、逐行映射、现有主档的完整前态/版本、排除项及经营期。预览接口不创建库存、流水或导入回执。可检查本地字节摘要：

```powershell
Get-FileHash .\docs\inventory\2026-10-05-photo-stock-review.csv -Algorithm SHA256
```

## 3. 人工确认目标余额并提交

```powershell
& $stockPython .\scripts\stock_import.py --api-url $api --username $operator --terminal-code $terminal apply --csv .\docs\inventory\2026-10-05-photo-stock-review.csv --mapping .\stock-photo-mapping.json --preview .\stock-photo-preview.json --output .\stock-photo-receipt.json
```

先显示所确认的预览，再要求键入 `APPLY ` 加预览中的完整 SHA256。只有确认一致才进入隐藏密码登录和提交。服务端在财务写事务锁内重新验证来源摘要、映射、余额、单位、版本和经营期，再一次性写入所有行；任何一行失败全部回滚。目标已等于余额时不写零数量流水，但保留盘点回执。成功后保留 CSV、映射、预览、回执作为一组证据。

输出文件必须使用新文件名，脚本不会覆盖旧证据。连接失败、HTTP 错误或本地保存失败不会自动重试：如请求可能已提交，保留原 CSV、映射、预览，用新的回执文件名再次执行同一 `apply`。服务器会依据全局来源 SHA256 返回原回执，不新建主档、不再次调账；不同请求编号、不同有权限的操作者或后续经营期也不使同一来源变成新盘点。返回的原回执仅说明当时已经完成，不代表当前余额仍等于盘点时数量。

若首次提交前发生出入库、单位/版本变化或经营期变化，旧预览被拒绝，重新预览并人工审核。已成功导入的来源不得改映射重用。更改 CSV（包括重新保存换行）会形成新来源身份，必须作为新的盘点重新审查；不要仅为绕过重复保护修改文件。已成功导入来源的再次预览会附 `already_applied_receipt_id`，并返回原来确认过的预览；它不是新的库存快照。

## API 约定

两个接口均要求 `inventory:write`、有效登录会话和原有入口/经营期/维护保护：

- `POST /api/inventory/photo-import/preview`：JSON 字段精确为 `source_base64`（原 CSV 字节的标准 Base64）、`source_sha256`（小写 64 位十六进制）、`mapping`。
- `POST /api/inventory/photo-import/apply`：在相同字段上添加 `confirm: true`、`preview_digest`、`period_id`，并发送 `Idempotency-Key`。已有幂等请求仍校验内容，不能用相同请求编号替换确认信息。

CSV 必须包含 `source_photo,row,name,category,base_unit,package_unit,units_per_package,package_quantity,basic_quantity,review_status`；可包含现有核对表的 `package_spec,original_quantity,original_unit,input_unit,notes`，拒绝其他未审核列、重复列、重复原始行号。完整核对表显式使用 `input_unit=base/package`，已审核行的原始数量/单位/输入单位列一旦提供就不能留空。只有简化格式缺少此列时，非空 `package_quantity` 代表包装输入，否则 `basic_quantity` 代表基本单位输入。基本单位和包装单位仅接受明确支持的单位：袋、瓶、条、个、套、块、支、桶、卷、包、盒、件、箱、升、毫升、克、千克；其他单位须先扩展审核契约，不猜测转换。

数量、系数和最终乘积精确使用十进制定点，绝对值小于 1,000,000,000，最多三位小数；目标余额可为零、不得为负，换算系数必须正数。超精度乘积直接拒绝，不做四舍五入。来源上限约 256 KB、证据行上限 500。错误包含 `STOCK_IMPORT_HASH_MISMATCH`、`INVALID_STOCK_IMPORT`、`STOCK_IMPORT_STALE` 以及原有权限/会话/维护错误。审计链记录操作者、终端、请求、原始字段、输入换算、前后余额/版本和来源摘要；没有新建数据库表或修改历史证据。
