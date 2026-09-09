# aipipe 渐进重构实施设计

状态：第一阶段实施契约。当前已实现能力以 CLI help、对应版本说明和原 Issue/PR/Checks 为准。接受阶段 A、B、C 依次实施；资源 upgrade、自动签发策略与轻量分发另行设计，不混入本批。

## 不变量

- GitHub 是任务账本；本地只有项目配置与非秘密执行参数。
- 保留两个 App、明确角色身份、单 Issue 分支、完整分页、当前 SHA 独立验收和原生 CI；不扩大权限或绕过保护。
- aipipe 不启动模型客户端。已获授权的宿主可以调度独立开发和验收上下文；使用外部工具时遵循用户选择。
- 正式资源只含通用规范与匿名测试；项目实例、凭据和业务记录留在各自项目。
- 每片实现、有效测试、help/规范和生成文件同交付；新版本同步安装产物和验证环境。

## A：可判定的 Review/merge 结果

新增可选参数 `aipipe github --result-json --role delivery --identity FILE -- pr review|merge ...`。参数在 `--` 之前，避免与传给 gh 的 `--json` 混淆。第一片只支持带身份的 Review/merge，不提供新的模型调度命令。

不传此参数时保留既有输出和退出码，包括 metadata 同步失败的旧行为。参数明确但所选操作不支持，或缺少身份时，写前拒绝。参数解析失败仍是 argparse 错误；成功解析后的结构化执行只向 stdout 输出一个 JSON 对象。

结果字段：

```json
{
  "schema_version": 1,
  "operation": "merge",
  "repository": "owner/repository",
  "pr": 7,
  "primary": {"status": "succeeded", "head": "FULL_SHA", "merge_sha": "FULL_SHA"},
  "metadata": {"status": "succeeded"},
  "recovery": {"scope": "none", "argv": []}
}
```

字段不适用时省略可选值，不造假 SHA。`primary.status` 为 succeeded / failed / unknown；`metadata.status` 为 succeeded / failed / not_run（C 阶段可增加 pending）。退出码 0 对应主操作已确认成功，1 对应明确失败，2 对应可能已写入但无法确认。主操作成功不等于整个业务交付完成。

- 本地校验、凭据缺失、写前读取失败：failed，远端主写入次数 0。
- 原生明确拒绝写入：failed；无状态码、超时、5xx、无效/缺失成功响应、写后回读失败或不一致：unknown。保守处理不确定写入，不把它误报“肯定没执行”。
- Review 只有写响应、commit_id 和后续 head 核对符合原语义时才确认成功；merge 仍核对 merged、merge SHA 和 head。
- 一旦确认主操作成功，metadata 失败不能改变 primary.status。recovery 只给 metadata 修复命令，argv 保留实际 project/config/credentials/identity 选择，避免恢复时串项目；不提供自动重做 Review/merge 的建议。
- unknown 的 recovery 仅给只读核对 PR/Review 的命令与原因，不自动重复原写入。没有可靠证据时保持 unknown，后续精确回读恢复可以再单独扩展。
- JSON error 使用固定分类和清洗过的资源/状态；不直接输出未知异常、请求正文、身份文件内容或秘密。已有 GhError 调用方保持兼容。

验收覆盖成功、metadata 失败、写前拒绝、403/422 拒绝、5xx/超时、响应损坏、回读不一致、head 变化，以及默认旧入口。通过真实角色完成一条带结构化输出的 Review/merge 闭环；故障写入用匿名夹具，不破坏真实保护。

## B：只读接手状态

新增 `aipipe status (--issue N | --pr N) --role developer|delivery [--offline] [--json]`。不依赖身份文件，不写配置、凭据、Git 或 GitHub。

输出版本化结构：repository、target、observed_at、head/base、Issue/PR 摘要、阶段及来源、角色检查结果、原生审批和必需检查、阻断与下一动作。unknown/pending/failed 必须区分。状态入口不等于业务验收，不批准、不合并、不自动关 Issue。

离线只报告本地可知配置、兼容性和当前检出；远端字段明确 unknown，不读 token 或 Owner 信息。在线只读取所选角色凭据，聚合既有事实与用途检查，避免要求接收者手动串联 inspect、doctor、metadata 和多个 gh 命令。

一次调用内部复用 repository 信息；不建立跨进程任务缓存。Issue -> PR 的关联沿用完整关联与歧义拒绝规则，不能只根据分支猜测。PR 当前 head 在读取结束核对，变化时状态不作为下一写入依据。checks 的缺失/排队/失败/非预期来源不能当 success，required check 和 review 只反映 GitHub 事实。

状态无法读取时仍给结构化阻断，不建议重建 App；新宿主、到期与权限错误分别定位。下一动作是建议，不授权执行。写入口仍在自己的流程中重新校验 head 与服务端规则。

验收覆盖 Issue 无 PR、Draft、退回、新提交、已合并与 main CI 失败、无关/多个 PR、缺失检查、角色错误、离线、版本不足、远端失败及重复调用零写入。Skill 的普通接手路径引用 status；细节只在错误对应规范中维护。

## C：事件同步与运行成本

新增显式 metadata 模式，缺省保留 inline，只有 Owner 已安装并验证可信默认分支 workflow 的项目才能选择 workflow。普通 Review/merge 在 workflow 模式下不再次写标签，结果标记 metadata pending；显式 metadata 核对/修复继续可用。阶段标签不是合并门禁。

事件路由显式忽略 tag、非任务分支和无关事件。逐任务计算差异并隔离失败，成功任务继续执行，最终总结未解决项并失败退出。扫描覆盖开放任务和有界近期关闭任务；人工历史修复独立。时间窗口、分页上限必须文档化，不能声称任意长时间漏事件都会自动恢复。

优化 facts：每轮 repository 信息只读取一次，已有关联 PR 时不再为阶段判断读取无用分支；保留改名分支、其他关闭关联、歧义拒绝与写后回读。

优先使用 GitHub 原生 concurrency 保证工作流写入按范围收敛；必须说明 pending 合并/取消和漏事件恢复，不声称解决所有跨 CLI 并发。Review 事件必须使用默认分支受信代码，不能执行或 checkout PR 代码；先验证该事件的凭据权限，再启用模式，不扩大 App 权限。

工具 CI 保留 PR 与默认分支 push 检查，去掉普通开发分支 push 的重复运行。仅在确认 required checks 不会永久 pending 后按路径分流；已有业务 CI 契约不变。需要改 workflow 时由 Owner 通过正常 PR 交付。

验收：当前匿名单任务/单 PR 夹具无变更读取从 6 次降到不超过 5 次；重复执行零写；一个坏任务不阻断好任务但最终退出失败；非任务事件零任务扫描；旧 inline 行为兼容；真实默认分支事件、显式巡检、合并后标签和分支收尾正确。

## 交付与回退

A、B、C 各有独立 Issue/PR，按顺序完成、独立验收并发布兼容版本；不在一个大 PR 里混改。每次发布安装产物、模板资源、生成文件与活动验证环境一致。

回退只恢复对应功能开关、旧兼容输出或已核实旧发布产物。不能通过回滚 CLI 重做已完成的 Review/merge；原 GitHub 事实和署名历史保留。原项目配置、业务源码与测试、计划、专属交接内容默认保留。
