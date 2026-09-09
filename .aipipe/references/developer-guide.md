# 开发者使用指南

安装、交互输入与可复制命令见 [CLI 使用指南](cli.md)。定稿后文档与交接仅在 GitHub 维护，见[文档与账本](documentation.md)。

## 开始使用

新项目可用 GitHub Template 建仓或下载 ZIP，保留 `.aipipe/` 隐藏目录；需求文档可以放在根目录 `docs/`。传统项目接入时复制 `.aipipe/` 后调用 `aipipe-init`，保留原有源码、文档、CI、分支和任务；不要将模板工具自测覆盖到原业务 CI。

已使用 aipipe 的项目直接调用 `aipipe-resume` 恢复。本机缺少凭据映射时只补映射。完整选择表见 [场景指南](scenarios.md)。

## 谁执行哪些工作

用户可选择任意 AI 开发工具与模型完成 App 初始化、开发文档设计、拆片和发布；aipipe 只提供 Skill、项目配置和执行工具。开发与验收使用独立上下文和不同 GitHub 身份，规划/发布可以使用 Delivery 身份。用户手工启动各工具。

在工具中直接要求读取对应 `.aipipe/skills/<name>/SKILL.md`；原生 Skill 发现方式见 [工具调用](tools.md)。不同角色可以由同一种软件的独立会话承担，也可以使用不同软件。

## 四个常见任务

**接入传统 Java 项目：**“读取 aipipe-init Skill；接入当前传统项目，登记现有 Maven 命令、默认分支、CI 和 App。保留现有方案，不生成新的开发文档，不发布开发任务。”

**只写开发文档：**“读取 aipipe-plan Skill，用我选择的当前模型，根据现有需求补齐接口和测试设计；本次只产出文档。”

**只发布既有计划：**“读取 aipipe-publish Skill，预览这份 batch.json，按本次授权发布到配置的仓库；复用已有设计，不重写方案。”

**续接原 PR：**“读取 aipipe-resume Skill，恢复 Issue #42 / PR #57，核对实际目标分支、交接 SHA 和测试；续接原分支。”

## 准备 GitHub 身份

Owner 用初始化 Skill 创建或复用两个 App，安装到选定仓库，登记 project.json，并把角色 token 映射配置到各自宿主。实际网页和命令见 [App 指南](github-apps.md)，可复制执行的 registry、GitHub 调用和测试命令见 [配置执行说明](configuration.md)。

App 注册、安装、签发 token、登记配置、验证权限是不同结果，逐项记录。没有账号授权时工具先准备字段和配置，Owner 完成登录/授权后继续；不能把文件生成说成 App 已创建。

## 日常开发与验收

开发者领取 Issue 后编号已知，新任务使用 `aipipe/issue-N`，已有分支继续原分支。实现和有效测试同 PR，正文填写 `Closes #N`、测试结果与 SHA。初始化中登记的命令通过 `aipipe run NAME` 执行，GitHub 操作通过指定角色执行；业务 CI 直接调用原生构建测试入口。

验收者核对实际 PR head，独立验证实现与测试。提交新代码后旧批准失效；通过并满足门禁后按[身份指南](identity.md)执行绑定当前 SHA 的即时 squash 合并，回读 GitHub 合并记录和开发分支删除。只处理一个任务或连续批次由用户选择。

## 保持可维护

配套文档、Skill 和脚本更新时一起核对；只升级模板不会替用户项目自动迁移配置。需要升级时先比较差异，保留实际 project.json、计划和项目约定。退出时按 [移除指南](removal.md) 移交 CI 与权限，业务代码和文档保留。

若要参与 aipipe 本身开发，参见 [维护与开发说明](contributing.md)。

doctor 的 ready 仅针对 ready_for 指定的用途。business_acceptance.evaluated 始终为 false：它不运行业务 CI、不证明测试有效或已独立批准。空项目可通过开发前置检查，同时显示原生命令尚未登记；正式验收仍按当前 PR 的实现、测试与原生 GitHub 门禁判断。

接手先 `aipipe inspect`：cli 字段报告真实入口、源码位置、运行版本、项目资源版本、内置源码版本与兼容性。新资源包含 `.aipipe/compatibility.json`；项目也可用 `config set --minimum-cli-version 0.3.0` 登记最低版本，两者取更严格值。版本不足时，在原生命令或角色凭据读取前停止；inspect/doctor 保留诊断结果。旧资源没有版本标记时显示未知，不自动标成新版。

升级使用已核实入口对应的安装环境，审查 Skills、project.json、plans 与定制差异；不覆盖用户内容。旧于 0.3.0 的 CLI 尚不识别该契约，接收者必须先自行核对 `--version` 并升级；不能声称新代码可以约束尚未更新的旧二进制。不会为了版本探测启动外部开发工具。

查看谁写了代码、谁验收或合并，使用 [执行身份指南](identity.md)：新提交的 Author 显示工具/实际模型，相关 PR/Review/发布和合并记录保存处理人。版本升级必须同轮同步测试项目；不能用切换全局入口代替项目资源更新。

## 任务元数据

阶段、PR 标签及 Issue 里程碑约定、Owner 工作流安装及手工修复见 [元数据约定](metadata.md)。新版本须同轮同步模板、全局 CLI、测试项目及生成的自动化文件。
