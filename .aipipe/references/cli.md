# aipipe CLI 使用指南

0.5.2 提供可安装的 Python CLI。Skills 负责理解任务和选择能力；CLI 负责确定性的配置、凭据和 GitHub 操作。模型、开发工具由用户选择并手工启动。没有固定的“初始化 → 设计 → 发布”流程。

## 安装一次，在各项目使用

需要 Python 3.9+。远端操作需要已安装的 gh 和 git；Owner 签发 App JWT 需要 openssl。先在可信环境用 `gh auth login` 建立 Owner 登录。包名为 `aipipe-workflow-cli`，命令名为 `aipipe`；当前没有发布到 PyPI，不使用 `pip install aipipe`。

从可信模板检出安装到独立环境：

```bash
python3 -m venv ~/.local/share/aipipe/venv
~/.local/share/aipipe/venv/bin/python -m pip install /absolute/path/aipipe-template/.aipipe
mkdir -p ~/.local/bin
ln -s ~/.local/share/aipipe/venv/bin/aipipe ~/.local/bin/aipipe
```

已有安装时先检查路径，更新使用该 venv 的 pip，不重新覆盖未知链接。确保 `~/.local/bin` 位于 PATH；也可直接使用完整命令路径。已安装 pipx 的用户可执行 `pipx install /absolute/path/aipipe-template/.aipipe`，升级也通过同一安装方式完成。wheel 包含 init 所需资源，运行时不依赖模板检出目录。

```bash
aipipe --help
aipipe --version
aipipe init --help
aipipe config set --help
aipipe auth issue-token --help
```

完整模板检出还保留 `python3 .aipipe/scripts/aipipe.py` 等旧命令包装，调用同一源码实现；CLI 接入传统项目只复制 Skills、模板、文档和配置，不复制一份 CLI 源码。因此传统项目使用已安装的 `aipipe`。

默认从当前目录向上寻找 `.aipipe/project.json`，遇到最近 Git 根目录即停止，支持 worktree；不会读取 CLI 安装仓库的项目配置。也可显式指定 `--project /absolute/project`。`--project` 与 `--config` 同时提供时必须指向同一项目。

## 独立选择初始化能力

`aipipe init` 在终端询问本次需要 repo、apps、credentials、checks 或 all。只询问缺少的信息；确认后执行。已有授权的自动化调用使用 `--apply --non-interactive`，不重复触发交互确认。非交互且无 `--apply` 时只展示改动范围；某些信息仍需只读查询 GitHub，不能把 init 当作完全离线命令。

| 场景 | 入口 |
|---|---|
| 创建自己的空模板项目 | `init repo --create` |
| 传统项目首次接入 | `init repo`，保留代码、文档和原生 CI，不生成方案 |
| 已有 aipipe 项目接手 | resume Skill；只按缺项调用 credentials / apps / checks |
| 仅修复凭据或换机器 | `init credentials`，已有 App 不重复创建 |
| 只补 App 创建或安装 | `init apps` |
| 只补合并设置和保护 | `init checks` |
| 只设计或只发布切片 | plan / publish Skill；不强制重新初始化 |

创建仓库的交互输入支持仓库名或 OWNER/REPO、创建或绑定、private/public、template/empty/source、App 创建或复用。只填仓库名时通过 `gh api user` 取得 Owner。默认模板是 `yes8080/aipipe-template`；使用者必须有该仓库访问权，或用 `--template OWNER/ACCESSIBLE_TEMPLATE` 指定自己的模板。

```bash
# 新项目：目标目录须为空，创建后克隆并生成配置
aipipe init repo --project /code/product --repo OWNER/product --create --visibility private --apply --non-interactive

# 空仓库而非模板；以后仍可放入业务设计 docs
aipipe init repo --project /code/product --repo OWNER/product --create --empty --apply --non-interactive

# 传统项目已有正确 origin：只接入，不重写方案
aipipe init repo --project /code/existing --apply --non-interactive

# 纯本地接入，不创建远端
aipipe init repo --project /code/existing --repo local --apply --non-interactive

# 已有本地 Git、尚无 origin：创建远端；只有显式 --push 才推送原代码
aipipe init repo --project /code/existing --repo OWNER/existing --create --source --push --apply --non-interactive
```

新项目的产品资料放根目录 `docs/`；已有项目沿用原位置。init 不生成业务开发方案，不创建里程碑或 Issue。复制资源仅补缺文件，现有 Skill 不被静默覆盖；升级时由维护者审查差异。

## App 注册、接入与凭据

```bash
# 创建或复用；网页注册与安装授权仍由 Owner 完成
aipipe init apps
# 导入既有角色；私钥始终在仓库外
aipipe init apps --role developer --app-id APP_ID --private-key /private/owner/developer.pem
# 已绑定项目只刷新短期凭据，不重新创建 App
aipipe init credentials --apply --non-interactive
aipipe auth issue-token --role developer
aipipe auth status
```

注册采用预填 manifest、本机一次性回调及 gh code conversion。Owner 完成登录、注册与选定仓库安装；CLI 读取实际身份、权限和 Installation，并签发单仓库角色 token。`--no-browser` 支持手工打开本机 URL，不能把 loopback 当作无人值守远程注册服务。中断后读取已有绑定和外部元数据续跑，不重复创建。

默认私有 App 恰好拥有对应角色权限，且 App 与仓库属于同一 Owner。共享 App 的 Owner 或完整权限不同，则先登记明确绑定，再由 Owner 运行：

```bash
aipipe auth trust-app --role developer --app-owner APP_OWNER --permissions-file /private/owner/permissions.json
# 确认实际 Owner、App ID 和完整权限符合本次授权后才保存
aipipe auth trust-app --role developer --app-owner APP_OWNER --permissions-file /private/owner/permissions.json --apply
```

permissions.json 是实际完整 App permissions 对象，非秘密；预览必须与真实 App 一致，并能提供当前角色。信任记录绑定当前仓库、角色、App ID、Owner 和权限；变化后停止重新授权。命令不修改 App 权限、不安装仓库、不签发 token。后续 token 只申请固定角色最小权限和当前仓库，核对返回权限后才保存。

```text
项目/.aipipe/project.json                      静态绑定与 credential_ref
~/.config/aipipe/owner/keys/<id>.pem           Owner 私钥
~/.config/aipipe/owner/apps/<id>.json          Owner 元数据与私钥引用
~/.config/aipipe/owner/trust/OWNER/REPO/*.json  共享 App 明确信任
~/.config/aipipe/tokens/OWNER/REPO/*.token     短期角色 token
~/.config/aipipe/credentials.json             引用到本机凭据的映射
```

敏感文件 0600。`--credentials PATH` 可更换仓库外 registry，其父目录是默认 Owner/token 根。日常角色不读取私钥；签发在 Owner 受信环境执行。文件移出仓库及清除环境变量都不能替代宿主账号/容器隔离。组织安装、审批和 SSO 仍取决于实际账号环境。

## CI 与已有保护

```bash
# Owner 先只读核对既有规则、传统默认分支保护和额外约束
aipipe init checks --audit
# 只设置 squash、auto-merge 和自动删分支
aipipe init checks --apply --non-interactive
# 首次配置：真实检查提供名称和来源，不必先有绿色业务测试
aipipe init checks --rules --check-name ci --check-sha FULL_SHA --workflow-path .github/workflows/aipipe-product-ci.yml --apply --non-interactive
```

`--audit` 不写 GitHub 或项目配置。通过有效分支规则接口读取仓库与组织规则，完整 Owner 视图核对 bypass、角色写入资格和传统默认分支保护；额外检查、审批或签名要求会报告，冲突停止。支持 legacy 主分支保护与 aipipe feature ruleset 组合，不自动迁移任意旧通配保护。

多个必需检查通过 `config set --checks-file FILE` 登记 JSON 数组，例如 `[{"context":"unit","integration_id":15368},{"context":"integration","integration_id":15368}]`，保存为 ci.required_checks。旧单检查字段继续兼容；多检查项目必须显式更新整个列表，不能用 --check-name 悄悄改变其中一项。

metadata 同步模式通过 `config set --metadata-mode inline|workflow` 登记。缺省 `inline` 保持 Review/merge 后即时同步；`workflow` 仅在 Owner 已通过普通 PR 安装并验证默认分支可信 metadata 工作流后启用，Review/merge 结果只报告 `metadata.status=pending`，由 GitHub Actions 后续同步。启用证据写在 GitHub Issue/PR，不在项目配置里增加运行账本或“已验证”布尔标记。

`init checks --rules` 核对每项来源，复用等价规则，只在无冲突时补缺。不会覆盖原规则、生成 YAML、业务测试或原生命令。规则和检查完整分页读取，后续页失败、重复或截断即停止；1000 页仍未结束会报错，不把未读完视为不存在。

Developer/Delivery token 没有 Workflows 写权限。Owner 或初始化 AI 先预置真实业务 workflow，首片提交代码、锁文件和有效测试；现有项目复用原生 CI。模板 `aipipe-template-checks` 只证明工具测试通过，不能代替业务 ci。业务未实现时 ci 失败可作为开发起点，不能当作业务已经验收。

## 就绪检查与离线工作

```bash
aipipe doctor --for plan --offline
aipipe doctor --for develop --offline
aipipe doctor --for review --offline
# GitHub 发布或正式角色交接前
aipipe doctor --for publish
aipipe doctor --for develop
aipipe doctor --for review
# Owner 初始化宿主具备两角色凭据，另用 Owner 登录读取完整保护
aipipe doctor --for handoff
```

输出的 ready 仅针对 ready_for：离线规划/开发/评审、GitHub 发布或相应角色交接。business_acceptance.evaluated 始终为 false，CI 执行、测试有效性与独立 Review 都不在 doctor 内验收。空项目可显示开发前置就绪，同时提示没有登记原生命令；不能据此合并 PR。

`--offline` 不读取凭据、不访问 GitHub、不运行命令，也不创建配置；已有命令会检查 cwd/argv。只允许 plan/develop/review，不能给 publish/handoff 加 offline 绕开远端条件。需要写入 GitHub 时切回相应角色检查。

App 无法读取完整 legacy 保护和 bypass 名单，develop/review 只验证可见条件；完整 handoff 由 Owner 审计，不给 App 增加 Administration 权限。Owner 看不到所需规则来源时停止，不假定其为空。

## 发布与放行

```bash
# 计划中的设计文件必须已提交，使用完整 40 位 SHA
aipipe publish --plan .aipipe/plans/batch.json --design-ref FULL_SHA
# 已授权发布才加 --apply；成功仍保持未放行
aipipe publish --plan .aipipe/plans/batch.json --design-ref FULL_SHA --apply
# 校验原计划、实际切片和交接前置条件；不带 apply 只读
aipipe release --milestone 1 --plan .aipipe/plans/batch.json --design-ref FULL_SHA
aipipe release --milestone 1 --plan .aipipe/plans/batch.json --design-ref FULL_SHA --apply
```

release 必须有发布时的计划与设计 SHA。它复用发布契约核对实际 Milestone、切片完整内容、依赖和重复标记；缺片、额外任务、错依赖或内容冲突均拒绝，绝不代替 publish 补发或改写。编辑器增加的末尾换行不算 Milestone 内容变更。检查成功后才改变唯一 released 标志，写后回读；重复执行也重新核验。它不运行开发工具或证明批次已经完成业务验收。

## 日常操作

```bash
aipipe inspect
aipipe config validate
aipipe status --issue 42 --role developer --json
aipipe run backend.verify
aipipe github --role developer -- issue view 42
aipipe push --role developer aipipe/issue-42
aipipe github --role developer -- pr create --head aipipe/issue-42 --body-file .aipipe/.runtime/pr.md
aipipe github --result-json --role delivery --identity REVIEWER.json -- pr review 42 --approve --match-head-commit FULL_SHA --body-file .aipipe/.runtime/review.md
```

以上使用真实命令名和已领取的 Issue。`status` 是只读交接入口；详细字段与 unknown 边界见 [status 只读交接状态](status.md)。PR 直接写 Closes #42；对应实现、测试和实际 SHA 一并交付。独立会话用 Delivery 验收，满足当前 required CI 与审批后普通合并；必须回读合并、Issue 关闭与分支删除。工具命令不计数返修轮次、不实施任务锁或自动启动客户端。

`github --result-json` 是带身份 PR Review/merge 的结构化结果入口，参数必须写在 `--` 之前，只支持 `pr review` 和 `pr merge`。不带该参数时保持旧输出和退出码；带该参数时，成功解析后的执行只向 stdout 输出一个 JSON 对象。`primary.status` 为 `succeeded`、`failed` 或 `unknown`；退出码 0 表示主 Review/merge 已确认成功，1 表示明确失败，2 表示可能已写入但无法确认。metadata 同步失败不会改变已成功的主操作，恢复命令只指向 `aipipe metadata`；unknown 只给只读核对命令，不建议重复写入。

## 版本、升级与手工接手

`inspect` 和 doctor 报告实际入口、Python/源码位置、运行版本、资源版本、内置源码版本与兼容性。新模板和新 scaffold 资源带 `.aipipe/compatibility.json`；项目可用 `config set --minimum-cli-version 0.3.0` 登记最低版本，两者取更严格值。版本不足时，在产品命令或凭据读取前停止，inspect 保留诊断。旧资源无版本标记时报告未知，不自动重标。

旧于 0.5.2 的二进制不能识别 `metadata.mode=workflow` 与 workflow metadata pending 语义；旧于 0.5.1 的二进制不能识别 `status` 交接入口；旧于 0.5.0 的二进制不能识别 `github --result-json` 结果契约。接收者须先核对 --version，升级所选入口。升级使用原安装环境，审查 Skills、project.json、plans 和定制差异，不覆盖现有文件。全局 CLI 与完整项目源码可不同版本，应明确本轮使用哪个入口。

PATH 不可见时先检查 `~/.local/bin/aipipe`；完整模板可用 `python3 .aipipe/scripts/aipipe.py`，传统 scaffold 不一定包含脚本。不同机器独立配置当前角色 token；过期由 Owner 刷新，继续原任务。

需要用户启动外部工具时，提供项目路径、Skill、Issue/PR、角色和入口检查命令的完整提示词；不自行启动。实际提示模板见 [工具接入](tools.md)。实现维护见 [contributing](contributing.md)，停用见 [removal](removal.md)。

## 代码作者与操作归属（0.4.0）

`identity create/show` 管理当前会话的非秘密执行声明，`commit --identity FILE --issue N --message-file FILE` 为已暂存的新代码记录实际作者。角色 GitHub 操作、publish、release 支持 --identity；完整示例、代提交、验收绑定 SHA 和合并作者保留见 [身份指南](identity.md)。启用 attribution.required 的项目要求身份并检查迁移基线后的新提交；本机姓名不再作为 Agent 新代码的默认署名。

## 任务元数据

阶段、PR 标签及 Issue 里程碑约定、Owner 工作流安装及手工修复见 [元数据约定](metadata.md)。新版本须同轮同步模板、全局 CLI、测试项目及生成的自动化文件。
