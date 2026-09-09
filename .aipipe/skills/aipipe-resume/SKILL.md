---
name: aipipe-resume
description: 区分已接入 aipipe 项目的恢复接手与传统项目的首次接入；从现有 Issue、分支、PR 与测试记录继续工作。传统项目先补接入配置，不要求重新生成开发方案。
---

# 接管与恢复

读取 [公共入口](../../AGENTS.md)、[status 只读交接状态](../../references/status.md) 和 [场景选择](../../references/scenarios.md)，先判断接手类型。只有模板文件存在但配置仍为空，不能视为项目已接入。

- 已使用 aipipe 的项目：核对已有配置与真实仓库，复用 Skills、命令、App 和交付记录，直接续接任务。只修复失效的本机凭据或配置，不重复完整初始化。
- 传统、尚未使用 aipipe 的项目：先用 `aipipe-init` 完成接入初始化，识别仓库、现有分支/PR、原生构建测试命令、已有 CI 与权限，生成项目配置；按本次操作需要接入 App 和本机凭据。初始化产出是配置及现状记录，不是新开发方案，不自动规划里程碑或重新批量发 Issue。
- 仅请求普通只读代码评审而没有要求接入 aipipe：可以直接分析，不擅自安装。若用户要求正式接入并交付，不能以“初始化可选”为由跳过传统项目的接入配置。
- 继续任务：优先读取已有 Issue、原分支、PR、当前 SHA、最近交接记录和 Checks。确认旧执行器已停止写入；未推送的工作不能仅靠聊天恢复，先保存并交接真实改动。
- 当前 PR 已合并：只做授权范围内的收尾或下一任务，不重新开分支开发相同需求。
- 当前 PR 待修复：在原分支继续，保留返修次数与已完成证据。已有分支无需改成 aipipe 命名，也不为恢复新建同一任务的第二个 PR。
- 已有项目没有 Issue：按用户要求先分析或开发；若目标是接入 GitHub 交付流水线，再按授权补一个具体 Issue，而不是重建全部历史任务。

确定下一步后按需转到 `aipipe-develop`、`aipipe-review`、`aipipe-plan` 或仅补某项配置的 `aipipe-init`。恢复报告写清仓库、原任务、分支、提交、已验证内容和下一步。用户手工选择并启动客户端，不探测 ZCode CLI 或建立跨工具启动器。

换工具接手前，在接收宿主以本轮角色运行 `aipipe doctor --for develop` 或 `--for review`。仓库已登记 App 不等于此机器有可用凭据；只补本机映射和过期 token，不重新生成方案或再建 Apps。

接手先 `aipipe inspect`：cli 字段报告真实入口、源码位置、运行版本、项目资源版本、内置源码版本与兼容性。新资源包含 `.aipipe/compatibility.json`；项目也可用 `config set --minimum-cli-version 0.3.0` 登记最低版本，两者取更严格值。版本不足时，在原生命令或角色凭据读取前停止；inspect/doctor 保留诊断结果。旧资源没有版本标记时显示未知，不自动标成新版。

升级使用已核实入口对应的安装环境，审查 Skills、project.json、plans 与定制差异；不覆盖用户内容。旧于 0.3.0 的 CLI 尚不识别该契约，接收者必须先自行核对 `--version` 并升级；不能声称新代码可以约束尚未更新的旧二进制。不会为了版本探测启动外部开发工具。

交接的必读材料仅来自目标仓库与 GitHub Issue/PR/Review/Checks；存在 `references/project-handoff.md` 时用它导航，再回读实际状态。仓库缺少正式设计或交接信息时，将缺项记录到原 Issue/PR，不要求接收者访问 Obsidian 或原聊天。详见[文档与账本](../../references/documentation.md)。

## 实际执行身份

发生写入前读取 [身份记录](../../references/identity.md)，创建本会话身份（工作角色 / 凭据角色：与本次实际工作相符），实际模型不可确认时写 unknown。提交代码时用 `aipipe commit`；相关角色写命令传 `--identity FILE`。不沿用其他工具的 Agent ID，不把人类宿主名当代码作者；恢复操作保留前任作者与交接记录。只读操作不强制创建身份。

## 阶段与元数据

读取 [元数据约定](../../references/metadata.md)。恢复时读分支、Issue 和 PR 的实际状态，检查 metadata；阶段标签不能替代依赖和验收证据。
