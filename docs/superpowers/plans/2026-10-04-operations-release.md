# 营业升级发布与维护 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立不泄密的Git源码基线，交付Win11 64位桌面包及安卓/网页更新，提供用户自执行、有恢复证据的ECS部署和精确清理流程。

**Architecture:** R1 先于所有业务代码；R2–R4 在 A/B/C 回归后执行。源码更新包、签名安装包、云端数据迁移和云端清理是四个独立门禁，不互相冒充完成；任何部署失败保留原文件及备份供用户核对。

**Tech Stack:** Git、Node test runner、PowerShell、Electron builder、Capacitor/Gradle、Docker Compose、PostgreSQL 17、Python pathlib/tarfile。

**Spec:** [设计第9–11节](F:/溪泉洗浴系统/docs/superpowers/specs/2026-10-04-operations-permissions-catalog-upgrade-design.md)

## Global Constraints

继承[总计划](F:/溪泉洗浴系统/docs/superpowers/plans/2026-10-04-operations-upgrade.md)。代理不连接 ECS、不部署、不清理，不读取签名私钥/JKS/生产 `.env`；用户自己运行命令和输入隐藏密码。没有真实恢复测试或没有原证书签名的构建不得宣称可正式发布。

- 本次单一目标win11-x64，Electron44.5.1/x64；原发布公钥keyId=b26477a9ed540ad0不换。现有其它目标配置/策略仍受保护，但不生成其它五种新包。
- 桌面建议0.4.3、Android1.2.2/code9，仅当实际线上没有更高版本；发布序号必须大于现有签名序号。
- 桌面 Ed25519 更新签名不等于 Windows Authenticode 签名；没有 Authenticode 时如实说明。
- Cloud SOURCE-WEB 包不含生产 `.env`、数据库、证书、私钥、APK、EXE、旧更新策略；安装包/策略分别由正式发布器验证上传。

## 文件责任及跨任务契约

- `scripts/lib/source-security.cjs`：显式源码白名单、敏感内容检查、拒绝重解析点，输出位置而非值。
- `scripts/build-operations-release.ps1`：本地检查和构建顺序，不签名、不 SSH；签名步骤交给用户。
- `scripts/lib/operations-release.cjs`：清单格式/版本/文件哈希/win11-x64唯一目标/原信任根校验。
- `scripts/build-operations-source.ps1`：复用 cloud-archive.ps1，生成唯一 SOURCE-WEB ZIP、SHA256、源码清单，不覆盖旧目录。
- `server/app/operations_backup.py`：C3创建receipt验证器；R3扩展maintenance CLI的备份和恢复后核验，不把未打入API镜像的deploy脚本当作Python导入模块。
- `deploy/cloud/scripts/operations_backup_verify.py`：用户部署入口驱动的隔离PG17容器编排；不自身承载公开API。
- `scripts/deploy-operations-upgrade.sh`：用户在 ECS 执行的预检→备份恢复→结构迁移→业务预览/应用→核验流程。
- `deploy/cloud/scripts/operations_cleanup.py`：只读盘点、验证允许清单、归档确认目标；不碰业务数据或自行猜测“无用”。
- `docs/releases/2026-10-04-operations-upgrade.md`：完整 PowerShell 用户操作、各实机验收和回滚指引。

### R1：Git 源码安全基线

**Files:** 修改 `.gitignore`；新建 scripts/lib/source-security.cjs、source-security.node-test.cjs、scripts/prepare-source-baseline.ps1；维护 docs/releases/2026-10-04-operations-upgrade.md 中 Git 范围。

**Interfaces:** `enumerateSourceFiles(root:string):string[]` 返回可提交的仓库相对路径；`scanSourceFiles(root:string,files:string[]):Finding[]`，Finding={path,line,rule}，不包含匹配正文；`assertSourceSafe(root,files):void` 非空 Findings 抛错。prepare-source-baseline.ps1 支持 `-ValidateOnly`，只显示安全文件/数量和位置，不自动提交、推送。

- [ ] **1. 写红测。** temp fixture 建安全模板、带假凭据的普通源码、private/key.pem、.env.production、APK、目录 symlink/reparsepoint；源清单不含后五类，敏感源码必须被阻止，报告不包含假凭据原文。

```javascript
test('source findings redact secret values', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-source-test-'));
  try {
    fs.mkdirSync(path.join(root, 'server', 'app'), {recursive:true});
    const fake = 'test-only-never-a-real-secret-984321';
    fs.writeFileSync(path.join(root, 'server', 'app', 'bad.py'), `PASSWORD = '${fake}'\n`);
    const findings = scanSourceFiles(root, ['server/app/bad.py']);
    assert.equal(findings[0].path, 'server/app/bad.py');
    assert.equal(findings[0].line, 1);
    assert.equal(JSON.stringify(findings).includes(fake), false);
  } finally { fs.rmSync(root, {recursive:true, force:true}); }
});
```

测试删除对象只能是本测试 mkdtemp 返回的已验证临时目录；不是实际项目路径。scanner 不接受目录穿越、绝对路径、任一祖先符号链接，不遍历 private/config/发布密钥目录。
- [ ] **2. 运行。** `node --test scripts/lib/source-security.node-test.cjs`，预期模块未定义失败；记录退出码。
- [ ] **3. 实现明确范围。** 首批只列 server/app、server/migrations、server/tests、client/src、client/electron、client/build、mobile/src、mobile/public 的安全源码；以及明确配置/lockfiles、Gradle wrapper/config/native源码、docs、逐一列出的 scripts 与 deploy/cloud 原型配置。不得把 scripts 全目录无条件加入，旧 ssh_*.py、诊断输出/上传日志排除。模板 `.env.example` 可纳入，实际 `.env*` 不可纳入。测试中虚构密码按 `server/tests/`、测试 fixture 路径规则豁免，不能让业务源码同名豁免。

```gitignore
# Additional private and generated artifacts
.env.*
!.env.example
!**/.env.example
*.pem
*.p12
*.pfx
*.key
mobile/android/.gradle/
mobile/android/**/build/
mobile/android/local.properties
deploy/cloud/nginx/active.conf
deploy/cloud/updates/
deploy/cloud/releases/
deploy/cloud/mobile/downloads/
deploy/cloud/mobile/assets/
deploy/cloud/web/
scripts/ssh_*.py
/六个版本安装包*/
```

按实际文件位置补充忽略下载目录；public更新**公钥**若后缀pem，也只能列明确公钥路径例外，不匹配私钥。扫描 key/password/token/DSN 私密常量、私钥块、云密钥格式；发现问题先定位整改，用环境引用代替，不把值写到聊天、日志或Git。静态检测只能减少泄密风险，不能保证发现一切秘密；人工检查允许文件清单。
- [ ] **4. 绿测、人工核对、安全加入。** 运行 scanner 测试及 `prepare-source-baseline.ps1 -ValidateOnly`；使用 enumerated 文件清单逐个 `git add -- <path>`，再扫描 index 对应内容；检查 `git diff --cached --name-only` 无私密文件和产物。已有用户修改逐项确认归属，不以 Git reset 清掉。
- [ ] **5. 提交安全基线。** `chore: establish reviewed source baseline without private artifacts`。保存实际 commit，后续任务每次只提交相关文件；不建远端、不推送。干净 clone 的依赖重建在 R2 检验。

### R2：完整回归、原信任根与可定位的安装包

**Files:** 新建 scripts/lib/operations-release.cjs、operations-release.node-test.cjs、scripts/build-operations-release.ps1、build-operations-source.ps1；修改 scripts/build-windows-release.ps1、client/build/windows-pack.cjs、runtime-download.cjs / runtime-download.node-test.cjs 以提供明确校验的离线缓存入口；修改 client/package.json / lockfile版本、mobile/version.json；复用既有 sign/build/publish/delivery scripts，不另造签名算法。

**Interfaces:** `validateOperationsManifest(root:string,manifest:OperationsManifest):void`；manifest包含schema=1/source_commit/desktop_version/android_version/code/build_id/trust_key_id，targets必须恰一条 `{target:'win11-x64',runtime:'44.5.1',arch:'x64',file,sha256,size}`，另有android/source_web/test_results/real_device_checks。build-operations-release.ps1固定传 `-Targets @('win11-x64')`，不改旧六目标基础工具；签名状态只从正式验证器得出。

本任务新增而非假称已存在的离线参数：build-windows-release.ps1 的 `-OfflineRuntimeCache <absolute-directory>`，传给windows-pack.cjs的 `--offline-runtime-cache <directory>`；验证pin后调用现有prepareRuntime(profile,runtimeRoot,{downloadArtifact})注入固定档案路径。仅显式离线模式禁网络，普通模式仍保持官方SHAS校验；产物evidence注明pinned-official-sha256或official-shasums256的真实来源，不虚构刚联网核实。

- [ ] **1. 写红测。** 构造假EXE格式fixture：缺win11-x64或混入其它目标、SHA错、runtime/arch错、旧信任根、低版本、重复文件和跨界路径拒绝；生产不能接受测试key/testOnly。

```javascript
test('delivery requires exactly the win11-x64 target', () => {
  const manifest = {schema:1, targets:[]};
  assert.throws(() => validateOperationsManifest('.', manifest), /win11|targets/i);
});
```

离线下载测试给 prepareRuntime 的 downloadArtifact 注入校验后的文件，不联网；缺文件/哈希不符即停止且不删原文件。缓存完整时注入的网络函数抛 `OFFLINE_NETWORK_FORBIDDEN`，构建仍需成功，证明没有暗中取 SHASUMS。
- [ ] **2. 运行。** `node --test scripts/lib/operations-release.node-test.cjs` 与 runtime-download 既有测试；预期缺manifest模块/离线分支失败。
- [ ] **3. 实现流水线。** 先执行总计划统一测试；额外跑 cloud-archive/更新policy/移动签名/兼容性测试。所有失败立刻停止，不构建签名产物、不上传。版本从实际源文件/线上由用户提供的签名策略快照核对，不默认重复序号1。离线缓存使用四个已核实官方档案 pin（filename、size、SHA256）；未知runtime拒绝，不能关闭TLS/校验或只相信缓存文件名。

仅需electron-v44.5.1-win32-x64.zip：157998329字节，SHA256=9b382492dcfee91f8f9e92c91f7972550a1b95d2299cac72279dab33a600d7db。其它历史runtime pins保留在既有兼容基础代码，不在本次下载/构建。

输出新的 `release/windows/0.4.3/<build-id>`；验证原公钥，不读取用户私钥。用户随后执行已有签名器：

```powershell
# $releaseRoot 和 $sequence 必须由本次实际构建索引、已有发布策略确定。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\sign-windows-release.ps1' `
    -ReleaseRoot $releaseRoot -PrivateKeyPath 'F:\溪泉发布密钥\desktop-release-private.pem' `
    -Sequence $sequence -MinimumVersion '0.4.3' -ReleaseNotes '修复授权、优化点单及正式营业价目表'
if ($LASTEXITCODE -ne 0) { throw '签名失败，停止发布' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\build-windows-delivery.ps1' -ReleaseRoot $releaseRoot
if ($LASTEXITCODE -ne 0) { throw 'Win11包校验或压缩失败' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\scripts\build-mobile-release.ps1' `
    -Version '1.2.2' -VersionCode 9 -MinimumVersionCode 9 -ReleaseNotes '正式营业升级与员工权限修复'
if ($LASTEXITCODE -ne 0) { throw '安卓原证书构建失败' }
```

上段是后续整理完整代码的接口示例，不代表已构建。最终先定义releaseRoot/sequence及SHA校验。Android原JKS隐藏输入，证书与旧APK一致。Win11 EXE集中到新的 `F:\溪泉洗浴系统\最新版安装包-0.4.3`，旧0.4.2六包文件夹保留。既有build-windows-delivery若强制六目标，新增显式Targets参数及目标集合校验测试；默认六目标旧契约不改，新wrapper指定win11-x64，不跳过单包签名/哈希校验。

SOURCE-WEB使用白名单源码和新构建web/mobile网页静态文件，排除下载包/更新策略；ZIP必须安全相对路径，复用FileShare.Read有限重试，不能关闭安全软件。源码包记录source_commit与清单；不伪称EXE/APK已签名。
- [ ] **4. 绿测和实机检查。** Node/PS发布测试、win11-x64目录校验、离线runtime校验及ZIP readback/SHA。实机Win11 x64登录/切换/返回/快捷键/覆盖更新/XP-58 USB打印；原证书APK覆盖、三位绑定管理员手机登录/全项目/报表/库存；网页及断线补拉。未测如实列出，不用构建通过代替实机。
- [ ] **5. 提交源码和发布文档。** `build: deliver verified multi platform operations upgrade`；不提交包、密钥、缓存和本地签名日志。manifest在release目录，文档只记录公开路径/哈希/状态。正式构建/签名校验全部通过后，检查不存在同名tag再给对应源码SHA打本地annotated标签 `desktop-v0.4.3` / `mobile-v1.2.2`（版本如实际递增相应更改）；同名tag存在就停止核对，不force替换。标签只说明交付源码，不冒称已部署，不自动push。

### R3：用户自执行 ECS 更新和真正备份恢复验证

2026-10-04阶段检查点：用户已完成历史pre-operations dump在独立PG17上的实际恢复，并回传285条审计/业务修订479；没有生成迁移后的应用receipt。当前补充的`operations_preflight.py`与`build-operations-deploy.ps1`只负责新SOURCE/WEB的已提交快照、完整ZIP校验和私有只读暂存，不是下面未完成的apply编排。备份create/verify-restored CLI已完成本地守卫回归；真实CLI PG17验证、Docker恢复编排、维护确认后的切换、三位手机实机和R4清理仍保留门禁。所有云执行仍由用户完成，代理不SSH。

后续检查点：新增`operations_deploy.py`、`operations_backup_verify.py`及独立`invoke-operations-cutover.ps1`用于用户已经验证的stage。预检上传器仍仅read-only，不把它改成隐式停服入口。正式工具先实际隔离PG17恢复/新schema/apply/角色伪造锁演练，通过后才执行生产DDL；经第二次真实恢复receipt和用户预览SHA确认后才能业务替换。已完成本地守卫/包装器回归，生产演练、切换及实机验收仍由用户执行，未将本计划总门禁标为完成。shell编排由标准库Python参数入口替代，避免再次多层heredoc拼SQL；固定路径/受保护引用及失败停止约束不变。

**Files:** 新建 deploy/cloud/scripts/operations_backup_verify.py、scripts/deploy-operations-upgrade.sh、scripts/upload-operations-upgrade.ps1、scripts/tests/test-operations-source.ps1；扩展C3 server/app/operations_backup.py、server/tests/test_operations_backup_receipt.py；修改 compose maintenance service、deployment_checks.py、app/__init__.py CLI注册；更新 release 操作文档。API service 不注入MAINTENANCE_DATABASE_URL。

**Interfaces:** 沿用C3 BackupReceipt={schema:1,dump_sha256,size,db_name,alembic_revision,business_period_id,business_revision,audit_checkpoint,restore:{status:'verified',pg_major:17,checked_at,checks_sha256}}。私有receipt持有路径，不经HTTP返回，权限0600。`validate_backup_receipt(connection, receipt_path:Path, expected_revision:str)->dict` 已由C3定义在app.operations_backup，必须比对当前DB、修订、经营期、revision、审计尾及dump实际文件。R3实现 Flask CLI `operations-backup create --output <private>` 与 `operations-backup verify-restored --database-url-env XIQUAN_RESTORE_DATABASE_URL --receipt <private>`；deploy/cloud/scripts/operations_backup_verify.py 调Docker启动隔离容器/调用上述CLI并整理恢复结果，只在用户维护环境运行。

上传脚本参数 `-BundlePath -ExpectedSha256 -EcsTarget -StageOnly -DryRun`：StageOnly本地验证不SSH；DryRun只显示非敏感目标和步骤；正常模式scp包后调用受控deploy脚本。shell入口 `--bundle /tmp/<basename>.zip --expected-sha256 <hex> --mode preflight|apply|verify`，不eval、不执行包中未经清单校验的任意命令。

- [ ] **1. 写红测。** 假receipt status=list-only、dump缺失/哈希错、schema/审计/业务revision过期、恢复库地址与生产同DB、receipt可被普通用户写、pack路径穿越都拒绝。fixture写私有小文件，错误不输出DSN或密码。

```python
def test_list_only_backup_cannot_authorize_cutover(tmp_path):
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'schema':1,'restore':{'status':'list-only'}}))
    receipt.chmod(0o600)
    with pytest.raises(BackupReceiptError, match='restore'):
        validate_backup_receipt(None, receipt, '20261004_catalog_packages')
```

PS source bundle测试使用隔离fixture和 `.env`哨兵，输出ZIP不得含env/updates/downloads/releases/active.conf。PG17集成恢复测试创建只用于本次测试的container/volume，无公网端口，恢复后余额、stock、历史订单、审计链及revision与备份快照相同，绝不能恢复进生产库。
- [ ] **2. 运行。** `python -m pytest server/tests/test_operations_backup_receipt.py -q`；`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test-operations-source.ps1`。缺模块/未隔离恢复应红测，pg_restore --list不算通过。
- [ ] **3. 实现严格阶段部署。** preflight只读清单与部署状态，确认真实路径、已有compose/env和四条私有DB配置存在但不打印值，单API worker/replica、磁盘/备份空间、包SHA、前一image ID、生产active.conf inode、已发布六target/APK策略文件和引用安装包哈希；保存private原文件快照和public策略引用清单。没有 .env 不生成默认凭据，明确停止。用户安排无人开牌维护窗口，不强清活跃账单。

apply顺序固定：

```bash
set -eu
cd /opt/xiquan/xiquan/deploy/cloud
# 以下脚本步骤由deploy入口内部实现，用户不粘贴生产密码。
docker compose --env-file .env -f docker-compose.prod.yml stop api
docker compose --env-file .env -f docker-compose.prod.yml --profile maintenance run --rm maintenance db upgrade
docker compose --env-file .env -f docker-compose.prod.yml --profile maintenance run --rm maintenance operations-upgrade preview --output /var/lib/xiquan-reset/operations/preview.json
```

上述三条之间不可省略：停api后用**旧schema只读SQL**核对所有open/settling/lost/重置任务阻塞→生成迁移前dump并在独立PG17容器真实恢复→使用唯一stage的新代码构建新image→运行显式maintenance结构迁移→再生成迁移后、业务替换前dump并真实恢复→产生C3所需receipt→preview→用户核对预览digest→maintenance apply(同connection owner+exclusive)→verify→恢复api并等health→发布新网页静态文件，验证策略文件和active.conf保持原样。任何一步失败停止，不自动清maintenance或启动旧binary碰新数据；保留两份备份和旧image，不`down -v`。

maintenance environment使用已有 `DATABASE_URL=${MAINTENANCE_DATABASE_URL}`（host .env映射，不额外让API读owner URL），新增只读备份URL、RESET_PRIVATE_DIR=/var/lib/xiquan-reset、PG17dump/restore路径和私有volume。维护执行app仅注册CLI，不启动reset/socket后台worker或短信。restore临时DB必须独立container/volume、随机名字；核对实际连接的server标识/DB，禁止只凭DSN字符串不同判隔离；私有密码通过进程环境/私有pgpass，不出现在命令参数和报告。

备份用custom格式，检查实际文件sha/size；恢复使用PG17 `pg_restore --exit-on-error --no-owner --no-acl` 到隔离库，核对行数+关键金额总计+逐个保留账户UUID/业务period/审计链。restore以schemaowner新建隔离表不需要生产角色，也不把生产密码导进临时容器。成功receipt原子写0600，失败不生成verified。有限重试可用于health，不可重复执行业务apply导致未审查副作用。

最终 PowerShell只用scp上传单一已校验包和小部署入口，再 `ssh.exe root@39.96.217.210 'bash /tmp/<verified-script> ...'`，先preflight再展示阻塞/预览、再用户确认apply。不得再使用PowerShell→SSH多层heredoc拼接SQL造成末尾SQL进数据库；部署入口是校验过的实际UTF8/LF文件。单引号/参数转义由固定basename/hex正则限制，不允许自由shell字符串。

SOURCE-WEB不覆盖已发布EXE/APK/downloads/releases/update feed，不修改Nginx active.conf绑定inode。随后用户独立执行现有publish-windows-release / publish-mobile-release；其失败只报各发布状态，不销毁成功业务升级。公开health检查只验证连接，不能代替权限/资金/目录实际测试。成功verify附新100号码、42正式项目+保留商品、余额/库存保留、最高管理员UUID、policy_version未意外全量递增及审计链结果。
- [ ] **4. 绿测与本地仿真部署。** 在隔离PG17/compose副本演练：配置缺失、坏ZIP、活跃手牌、restore失败、迁移失败、apply中断均停止且原数据/证据可恢复。执行合规日志不含DSN/密码；shell语法检查、PS语法解析、stageOnly无网络。回滚文档说明：先停写核对，新业务尚无真实写才可在用户明确批准后恢复dump与对应旧image；已有真实营业写入时不得盲恢复丢掉新账单，先人工审计。代理不执行生产试验。
- [ ] **5. 提交。** `ops: add user run staged upgrade with verified database restore evidence`。给用户完整分段PowerShell、预期输出、错误停止条件、公开包路径/哈希，不要求用户猜文件名或数据库密码。

### R4：盘点、允许清单和可恢复 ECS 清理

**Files:** 新建 deploy/cloud/scripts/operations_cleanup.py、server/tests/test_operations_cleanup.py；更新发布文档。

**Interfaces:** `inventory(project_root:Path,release_manifest:dict)->dict` 只读；`validate_allowlist(inventory_path:Path,allowlist_path:Path)->list[Path]` 要求清单digest一致且路径/hash/size/mtime未变；`archive_approved(paths:list[Path],archive_root:Path)->dict` 创建唯一tar+sha+原路径manifest，readback成功后才允许移动原目标至同文件系统 quarantine。CLI `inventory --output <private-json>`、`archive --inventory <json> --allowlist <json> --confirm archive-approved-paths`；永久删除不是自动阶段，必须另有用户对准确路径的确认。

- [ ] **1. 红测保护边界。** 临时project fixture中的旧源码ZIP可被候选盘点；生产env/备份/证书/数据库路径、任意symlink祖先、根目录/..、当前安装包、rollback安装包、任意policy引用安装包都不能成为允许目标；文件在盘点后变动拒绝归档。失败不移动原文件。

```python
def test_protected_env_is_never_cleanup_candidate(tmp_path):
    root = tmp_path / 'xiquan'
    root.mkdir()
    (root / '.env').write_text('TEST_SENTINEL=not-a-secret')
    report = inventory(root, {'targets': [], 'android': {}})
    assert all(item['path'] != str(root / '.env') for item in report['candidates'])
```

- [ ] **2. 运行。** `python -m pytest server/tests/test_operations_cleanup.py -q`，预期缺清理模块；所有测试只针对tmp_path。
- [ ] **3. 实现默认保护。** resolve严格限制在真实projectroot下指定release/staging临时区域，以及明确本次上传的 `/tmp/<verified-basename>` 单文件。绝不把 `/`、`/root`、`/opt`、workspace根、$HOME或glob当递归目标。禁止symlink/reparsepoint及跨设备目录移走；所有祖先与lstat校验，归档/移动之前再核对inode/hash，发生变更立即停止。候选规则仅为已被新bundle替代且不在依赖manifest中的构建残留/上传ZIP，未知文件标“待人工判断”而非删除。

保护所有 `.env*`、私钥/证书、Docker volumes、postgres_data、reset_private、/opt/xiquan-backups、审计证据、Git .git、当前及回滚源码/image/安装包、所有策略引用路径、nginx active.conf；禁用docker prune/system prune/volume rm。读取磁盘容量不等于有权删除。archive报告展示确切路径/大小/原因供用户审批；只有用户确认该批精确路径后才运行archive。归档保存恢复manifest和SHA，readback验证完整，默认保留quarantine和archive，不自动永久清空。

```python
resolved = target.resolve(strict=True)
if resolved == project_root or not resolved.is_relative_to(project_root):
    raise CleanupError('outside approved project subdirectory')
if any(p.is_symlink() for p in (target, *target.parents)):
    raise CleanupError('symlink cleanup target forbidden')
```

具体路径保护以allowlist和protected references为主，上段只是基础边界检查，不能据此允许整个项目树。任何删除需后续显式准确路径授权；原用户“删没用的”不足以跳过清单。归档后立即说明原位置移到哪里、如何恢复，不将已归档说成永久删除。
- [ ] **4. 绿测与清单输出。** 通过path/hash/TOCTOU失败和恢复readback测试；在隔离目录演练restore manifest能重建原文件及权限；inventory无网络无写业务。最终生产步骤由用户SSH盘点，把候选清单返回给用户，再等准确批准；没有批准如实标“清理待确认”，不影响新版本交付。
- [ ] **5. 提交。** `ops: protect live data and releases during approved recoverable cleanup`。执行结束记录Git commit和所有测试/实机/签名/部署状态；完成范围区分本地代码、安装包、线上升级与清理。

## 发布门禁与交付形态

- [ ] 设计16条验收均有映射；A/B/C/R完整回归，无财务/权限错误。
- [ ] SOURCE-WEB ZIP + SHA256 + 本次source_commit；不是包含测试签名的正式安装包。
- [ ] 用户可找到Win11-x64 EXE集中目录、Windows bundle目录、Android APK绝对路径；签名/未签名状态清楚。
- [ ] 完整 PowerShell先验证包再上传，出错停止；远端固定工作目录，所有密码隐藏输入。
- [ ] 只读盘点清单已生成，确切清理路径批准后可恢复归档；从未自动删数据库、备份、私钥或运行时依赖。
