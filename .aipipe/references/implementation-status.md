# aipipe 实现与验证范围

本文描述通用工具能力，不代表某个接入项目已经初始化、放行或完成业务验收。执行进度在 [aipipe Issues](https://github.com/yes8080/aipipe-template/issues)，资料归属见[文档与账本](documentation.md)。

## 当前资源版本

0.5.3 修复同步合并已知拒绝的结果分类，并增加不含凭据及原始响应的 API 请求上下文和错误类型；源码、安装 CLI、生成 automation 均有脱敏及单次写入回归。网络瞬时失败的历史根因仍需真实诊断证据，不因诊断增强便宣称已修复网络。

0.5.2 新增显式 metadata inline/workflow 模式、Review 信号 workflow、workflow_run 原生 run 事实核验、可信默认分支同步、事件路由减量、开放加近期关闭巡检、显式历史修复窗口和逐任务失败隔离。0.5.1 新增 `status` 只读交接状态，覆盖 Issue/PR 关联、角色诊断、原生 Review、required checks、merge commit checks、离线与 unknown 边界。0.5.0 新增 `github --result-json` 结构化结果协议，覆盖带身份的 `pr review` 与 `pr merge`。候选实现和验收状态以对应 GitHub PR、CI 与独立 Review 为准；本文只描述通用工具能力和验证范围，不提前替代合并结论。

历史基线：0.4.6 已通过独立验收并合并，见 [PR #16](https://github.com/yes8080/aipipe-template/pull/16)，合并提交 `857a0e453aacdd1162f28efccb9501b87d42b13a`。该版本工具测试为 163 项；后续版本的证据以各自 PR 与 CI 为准，不用此处的历史数量代替当前检查。

| 能力 | 实现与使用入口 |
|---|---|
| 独立初始化、传统项目接入、配置保留 | `initialize.py`、`context.py`、`config.py`；[场景](scenarios.md)、[CLI](cli.md) |
| App 注册引导、复用、安装读取、单仓库短期凭据 | `manifest.py`、`owner_auth.py`、`credentials.py`；[App 指南](github-apps.md) |
| 原生命令执行与角色 gh / api / push | `runner.py`、`github.py`；[配置](configuration.md)、[测试](testing.md) |
| 批量切片预览/发布、固定设计版本、依赖与重复执行核对 | `publish.py`；plan / publish Skill |
| 按用途 doctor、批次完整性与放行 | `readiness.py`；[开发者指南](developer-guide.md) |
| 原保护只读审计、多检查、分页与版本契约 | `policy.py`、`compatibility.py`、`github.py`；[维护指南](contributing.md) |
| 实际作者与处理人、SHA 绑定 Review、squash 来源、结构化结果与恢复上下文 | `identity.py`、`runner.py`；[身份指南](identity.md) |
| Issue/PR 阶段、标签及仅 Issue 计里程碑 | `metadata.py` 与生成运行文件；[元数据](metadata.md) |
| 六个独立 Skill、Issue/PR 模板和人读指南 | `skills/`、`templates/`、`references/`；入口 `.aipipe/AGENTS.md` |

Python 唯一源码位于 `../src/aipipe/`。正式分发资源只包含通用契约与回归，不包含下游项目的交付清单、资源实例或测试报告。

## 已覆盖的关键回归

- 初始化部分完成、角色就绪、离线边界、原保护读取、共享 App 授权与完整分页；对应 `../tests/test_readiness.py`、`../tests/test_policy.py`、`../tests/test_shared_app.py`、`../tests/test_pagination.py`。
- 发布重试、完整批次放行与配置诊断；对应 `../tests/test_publish_batch.py`、`../tests/test_release_batch.py`、`../tests/test_configuration.py`。
- 本地 Git / 裸仓库覆盖 squash 后续片、旧历史边界、错误提交拒绝及身份保留；对应 `../tests/test_identity.py`。
- 关闭引用的完整扫描、真实形状事件、索引延迟与冲突拒绝；对应 `../tests/test_closing_contract.py`、`../tests/test_metadata_events.py`。
- 0.5.2 对事件同步与成本做回归：单 Issue/PR 事实读取不超过 5 次、Review 信号零写、workflow_run 只按 run id 重读原生 facts、缺字段或 PR 关联缺失不可判定且不全扫、跨仓库/非默认 base 跳过、schedule 覆盖 open 与近期 closed、dispatch history 与近期窗口分离、扫描截断可见但不阻断已发现任务、workflow metadata pending 不 inline 写标签、生成 workflow 无 PR checkout/artifact/cache；对应 `../tests/test_metadata_events.py`、`../tests/test_metadata.py`、`../tests/test_result_json.py`。
- 0.5.1 对 `status` 做只读回归：Issue 无 PR、Draft/退回/head 变化、native reviewDecision 缺失、rules 不可读、required checks 结果与来源、commit status 同名约束、merge commit checks、角色错误、离线、版本不足和坏配置；对应 `../tests/test_status.py`。
- 0.5.0 对带身份 Review/merge 的 `github --result-json` 做结构化结果回归：写前失败输出 `failed`，写后不能确认输出 `unknown` 和只读恢复命令，metadata 失败保留主操作成功，恢复 argv 使用实际绝对上下文；对应 `../tests/test_result_json.py`。
- 0.4.6 对重复 DELETE 标签的 404 做完整回读确认，仍拒绝标签存在、读失败和其他错误；对应 `../tests/test_metadata_delete_race.py`。未记录 REST 资源的历史 404 不应统一归因，调查边界见 [Issue #14](https://github.com/yes8080/aipipe-template/issues/14)。

离线夹具、工具安装测试和真实 GitHub 集成分别提供不同证据；工具测试不能证明业务测试有效或 AI 上下文独立。各项目的真实审批、CI、合并和收尾证据保留在原项目 GitHub，通用验证方法见[初始化验收方法](initialization-validation.md)。

## 待验证与能力边界

Vue / Java / 大型混合仓库已有接入说明，但不能据此声称全部场景已完成业务闭环。Windows、远程无浏览器、组织 SSO、密钥丢失与轮换、大型批次时长、多模块环境、跨工具长期续接仍需分别验证。实施任务登记到 GitHub，本文件不维护另一张待办表。

当前不提供常驻调度、任务数据库、原子 Claim/租约、模型路由、客户端启动器或跨仓库原子合并。也没有常驻续签、原生 Skill 自动安装器、upgrade/uninstall CLI 或按阶段收窄 Delivery 权限。token 到期由受信 Owner 环境刷新；模型和宿主调度由用户选择。

每仓库一个活动切片、最多三轮返修、独立上下文属于 Skill 约定。身份是执行者声明；环境变量清理不是操作系统凭据隔离。完整命令以 `aipipe --help` 与[CLI 指南](cli.md)为准，plan/develop/review/resume 是 Skill，不是同名 CLI 命令。
