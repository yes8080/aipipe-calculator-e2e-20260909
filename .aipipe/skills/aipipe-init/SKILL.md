---
name: aipipe-init
description: 按需初始化或接管 aipipe 项目，创建或复用 GitHub Apps、补齐安装和非秘密项目配置，或单独配置 CI 与分支规则。用户要求接入、初始化、修复凭据或补齐仓库设置时使用；分析、规划和本地开发不以本技能为固定前置。
---

# aipipe-init

为用户当前指定的仓库补齐所需能力，不把项目推入固定初始化阶段。可独立处理 App、安装、项目配置、CI 或 rules 中任一项，也可接管已有项目。

传统项目首次接入 aipipe 时执行接入初始化：识别并保留原有架构、文档、任务、分支、CI 和测试入口，生成项目配置与所需凭据绑定。**不生成开发方案、不重新编排里程碑或发布历史任务。** 已接入项目的换机器、换工具或配置修复仅补缺项。各类任务选择见 [场景清单](../../references/scenarios.md)。

先确定目标项目根目录；从 [aipipe 统一入口](../../AGENTS.md) 读取项目约定。详细网页字段、权限、token 命令和规则示例见 [GitHub App 与仓库设置](../../references/github-apps.md)，只读本次需要的部分。若本技能由全局工具转发调用，以上资源应从目标项目 `.aipipe/` 解析，不能修改技能安装目录里的配置。

## 工具选择

优先用 `gh` 专用命令；无专用命令时用 `gh api`；仅在 GitHub 必需授权或接口不支持时打开对应网页。仓库设置、规则、App / Installation ID 查询和配置回写由工具完成，不把可自动化步骤交给用户逐项填写。具体能力与身份限制见 [CLI 引导与 gh 操作表](../../references/github-apps.md#01-cli-引导优先使用-gh)。

先运行 `aipipe --help` 和 `aipipe init --help`，通过 inspect 核对实际入口、资源版本与最低 CLI 要求；未安装时按 [CLI 指南](../../references/cli.md) 安装，模板完整检出也可用 `python3 .aipipe/scripts/aipipe.py`。当前版本的 repo、apps、credentials、checks 可独立调用；用 `--project` 明确目标。非交互执行需显式参数；已获授权的操作使用 `--apply --non-interactive`，不要因向导默认确认重复向用户询问。Owner 登录、App JWT 和角色 installation token 分开传给子进程，初始化权限不扩散到日常开发身份。

当用户要求“初始化后交给其他开发工具”，交付范围包含可接手的角色身份、凭据、分支与 PR 权限以及合并门禁。流程可组合不等于忽略这些交接条件。仅要求离线规划或局部配置时仍只做该范围。

沙箱内 gh 报登录无效或 DNS 失败时，先在已授权的正常网络/凭据环境做只读验证，区分执行环境限制和真实失效；不要直接要求重新登录。自动审批拒绝操作后，说明具体动作、缺少的授权范围和审批原因，准备可审查的最小变更再请求该范围授权；不得自行改用 Owner 身份冒充 Delivery 或把不完整接入宣告完成。

## 按需读取与复用

- 读取目标项目 `.aipipe/project.json`（若存在）、Git remote、现有工作流、项目原生测试命令；通过可用的只读身份查询仓库实际默认分支、App/安装及现有 rulesets。
- 用户只要求某个局部能力时，只补该项。已有仓库、可用 App、安装、业务 CI 和保护规则直接复用，不强改默认分支或 CI check 名称。
- 缺少远端身份不影响分析、规划和本地开发。只暂停确实需要该角色身份的 GitHub 写入，并明确缺少哪一项；不要要求先完成全部初始化。
- 续跑先读配置与远端事实。按 App ID/slug、Installation ID 与仓库选择查找已有对象；创建已成功而配置尚未记录时先查网页，不重复创建 App、安装或 ruleset。

## 创建或补齐 App

本方案通常使用 Developer 与 Delivery 两个角色身份；只为本次缺少的角色操作。

1. 先检查仓库外 Owner 元数据（不读取或输出私钥内容），让 `init apps` 复用既有 App；`auth status` 失败只说明本项目本机凭据不可用，不代表没有 App。对已有 App 核实 Owner、权限、Installation 与选定仓库。修改复用 App 的权限可能影响其他项目，不把本仓库接入授权扩大为其他安装的权限变更。
2. 没有可用 App 时，使用 `aipipe init apps` 预填 manifest 并交换 code；回调不可用时按参考字段处理。登录、2FA、注册或安装授权交给 Owner 完成，随后由工具读取实际编号、保存凭据并继续，不要求用户反复复制字段。
3. App 用于 installation 身份，关闭 Webhook Active，不新增 webhook 调度或用户 OAuth。manifest 握手允许一次性本机回调，完成即退出。Owner 持有私钥，仅安装到选定仓库；已有安装增加仓库的 API 身份限制按参考文档处理，不为便利强制新建长期 PAT。
4. 用户已授权本次创建、安装或修复时，完成该范围内必要操作，无需重复确认同一决定。未实际完成的网页步骤不得标记完成。

默认新 App 与角色 token 的权限：Developer 为 Contents Write、Pull requests Write、Issues Read、Actions Read、Checks Read；Metadata 自动 Read。Delivery 相同，但 Issues 为 Write。两者不授予 Workflows、Administration、Commit statuses 写权限。

共享 App 的 Owner 或完整权限不同于默认角色时，先用 Owner 的 `auth trust-app` 按实际 ID、Owner 和完整权限预览/登记仓库外信任，之后仍签发最小角色 token。不修改共享 App 原权限；详细字段见 [CLI 共享 App 接入](../../references/cli.md#app-注册接入与凭据)。

## 登记非秘密项目配置

执行项目内 `aipipe config set --help` 确认接口，然后使用 `--repo`、`--default-branch`、`--role`、`--app-id`、`--installation-id`、`--slug`、`--credential-ref` 按角色更新。实际检查已经确定时再传 `--check-name` 与 `--workflow-path`。

`config set` 只合并静态字段；创建和接入 App 使用独立的 `init apps`，后者自动回写实际编号与凭据引用。保留另一角色与已有配置；仓库、默认分支和 ID 来自实际读取，不编造缺失值。

记录现有原生测试/构建入口到 `commands`，使用 `--commands-file` 合并生成配置；把用户选择的规划、开发、验收工具和模型记录为可选 `preferences`，使用 `--preferences-file`。不指定时由用户当前工具处理，不硬编码 GPT-6 或某个厂商。配置执行器从 `commands` 运行已有命令，业务 CI 仍直接调用原生入口。

- `.aipipe/project.json` 可记录 `repository`、`default_branch`、实际 CI 引用，以及 `apps.developer` / `apps.delivery` 的 `app_id`、`slug`、`installation_id`、`credential_ref`。
- `credential_ref` 仅引用 Owner 外部凭据入口。私钥、token、Client Secret 及其编码不进入项目配置、Git 或 agent 工作目录。
- 运行状态不写进该文件。需要记录当前接入待办且本次授权包含该操作时，查找并更新已有初始化 Issue；确实没有才创建。

## 签发与使用角色 token

Owner 在受信任环境中运行 `aipipe auth issue-token --role developer` 或 `--role delivery`；从项目绑定和仓库外 Owner 元数据读取编号与私钥，刷新限当前仓库的短期 token，并原子更新外部 registry。也可用 `aipipe init credentials` 补齐两角色。导入外部私钥用 `init apps --role ROLE --app-id ID --private-key PATH`；私钥与 token 始终在项目外，文件权限为 `0600`。

宿主应仅提供本轮角色 token；CLI 按 credential_ref 向单次 gh/git 子进程注入。私钥与另一角色 token 的不可访问性需要宿主账号或容器边界保障，普通同账号文件不能形成这种隔离。当前 `delivery` 是完整 Delivery 权限，不声称已实现阶段子权限。token 过期只影响后续认证动作，Owner 可重新签发；不新建常驻凭据服务。

验证读取时使用 `gh api installation/repositories` 等支持 installation token 的接口。Git 推送采用 HTTPS 与正确角色凭据，不依赖个人 SSH key 或个人 token 回退。

面向其他 AI 工具的实际调用入口为 `aipipe`。按 [配置与凭据规范](../../references/configuration.md) 建立仓库外 registry，将 `credential_ref` 映射到本机环境变量或 token 文件；执行器只给当前 GitHub 子进程注入指定角色 token，产品检查清除声明的凭据变量。先核对配置，再用一次授权的只读 GitHub 操作验证接入，不在日志中显示 token。

## CI 与规则是可单独处理的工作

既有项目先用 `init checks --audit` 只读核对保护和冲突；支持多个 required_checks 与传统主分支保护组合，不覆盖原规则。App 看不到管理字段时，完整核验仍交由 Owner。

如果本次要求配置 CI，优先复用真实业务工作流与测试命令。仅新增的 aipipe 自有工作流文件使用 `.github/workflows/aipipe-*.yml`；GitHub 工作流不能整体移入 `.aipipe/`。模板自检 `aipipe-template-checks` 不代替业务 CI，不把它重命名为 `ci` 假装业务验收已经存在。

Developer/Delivery 都没有 Workflows 写权限。空项目要直接交给 Developer，Owner 应在初始化时预置调用约定原生命令的业务工作流，实际代码、测试和锁文件由首片交付；缺应用或缺测试时工作流明确失败。不能将新建或修改 `.github/workflows/` 作为 Developer 独自完成的任务，也不默认扩大 App 权限。已有保护项目的工作流变更遵循原 PR 审批，不能关闭保护。

工作流的第一次真实运行即使因业务尚未实现而失败，也能提供 check 名称和来源证据；据此配置 required CI 与角色规则后，Developer 可以开始首片。业务检查成功与独立审批仍是合并条件，不能为“初始化完成”造必过用例。

`aipipe init checks --rules --check-name NAME --check-sha FULL_SHA` 会读取实际检查来源，复用等价规则，或在无冲突时创建缺项；现有规则不兼容时停止，人工审查后再适配。该命令不生成或替换业务工作流。需要保护规则时，缺项按参考文档补齐：

- 主分支质量规则：required PR、独立审批、旧审批失效、真实 required CI，两个 App 无质量 bypass。
- 主分支更新资格：Delivery 仅以 For pull requests only 获得例外。
- `aipipe/issue-*` 创建与更新资格：仅 Developer 获得 Always allow 例外；不限制开发分支删除。

Owner 确认真实 required CI 与独立审批规则生效前，Delivery 不合并；不通过开放主分支给 App 来绕过这项缺口。这个合并限制不影响规划或本地开发。既有业务 CI 若已满足要求，直接引用现有证据，不强制重新初始化。

## 交付检查

初始化宿主执行 `aipipe doctor --for handoff`：两角色绑定、实际 bot 身份、各自单仓库 token、远端工作流及质量/角色保护均核实后，才能报告可跨工具接手。该检查不宣称业务测试通过。局部任务可用 `doctor --for plan` 或 `--for publish`，结果不能扩大解释为可开发/可合并。

已发布批次使用 `aipipe release --milestone N --plan FILE --design-ref SHA --apply`，在初始化宿主以 Delivery 身份放行；命令会做两角色交接检查，并只读核对原计划、切片完整性、正文及依赖。缺片、重复或冲突时停止，不自动补发。缺项先补齐，原有 Issues 保留，不重复发布。接收端 Developer 使用 `doctor --for develop`，验收者使用 `--for review`，各自只读取自己的 token；新机器/容器仍需要对应角色的本机映射。过期由 Owner 的受信环境刷新，不给 Agent 另一角色 token 或私钥。

## 交付事实

完成后报告本次新增、复用或修改的对象和项目配置路径；分别注明本地已写、远端已确认和尚待 Owner 操作的事项。不要把 App 注册、安装、token 签发、CI 成功或保护生效混为一个“全部就绪”状态。

首次实际业务 PR 可验证角色推送、独立审批、CI 阻拦与合并后删除分支。只补局部配置时不要求完整流水线演练；对未覆盖的行为如实保留待验证项。

GitHub 对 App 读者隐藏 ruleset 的 bypass 名单；字段缺省不等于空名单。完整 `doctor --for handoff` / release 由初始化宿主使用已登录 Owner 的只读规则查询完成，同时以两 App token 验证身份；开发/验收检查只验证本角色可见规则，绝不回退 Owner 执行业务写入，也不索取管理权限。

## 实际执行身份

发生写入前读取 [身份记录](../../references/identity.md)，创建本会话身份（工作角色 / 凭据角色：maintainer / 已授权维护账号），实际模型不可确认时写 unknown。提交代码时用 `aipipe commit`；相关角色写命令传 `--identity FILE`。不沿用其他工具的 Agent ID，不把人类宿主名当代码作者；恢复操作保留前任作者与交接记录。只读操作不强制创建身份。

## 阶段与元数据

读取 [元数据约定](../../references/metadata.md)。按需独立执行 `aipipe init metadata`，由 Owner 审查生成文件并通过 PR 安装；主分支未包含工作流时不能称为自动同步已启用。
