# 代码作者与实际处理人

CLI 0.4.1 在本地提交、PR、Review、批次发布、放行及 squash 合并中记录执行身份。GitHub App 继续隔离权限；工具、模型和会话是执行者声明，不能由 App token 或 GitHub Verified 标记证明。

## 谁写了代码

普通提交的 Author 是 `工具 / 实际模型`，例如 `codex / unknown`；Committer 是实际创建提交的执行者，并附工作角色。邮箱采用 `<Agent UUID>@agents.aipipe.invalid`，这是不投递邮件、不冒用个人或 bot 账号的声明地址。GitHub 的 push、PR、Review 账号仍由实际角色 token 决定。

提交说明包含 Aipipe-Agent、Tool、Model、Role、Credential-Role、Issue trailers。不同作者与代提交者分别记录；多作者通过 Co-authored-by 和对应身份 trailers 保留。只对当前 Git 子进程设置署名，不修改全局或仓库 user.name/email，不自动暂存文件，不重写历史。

工具已确认但模型不可见时写 unknown，不能抄 project.json.preferences 作为实际运行模型。一个独立上下文生成一个 UUID；换工具、模型、角色或独立会话生成新身份。同一上下文重试可复用其明确的文件路径，不使用共享 current-agent 指针。

## 创建本会话身份

```bash
aipipe identity create --tool codex --model unknown --role developer --credential-role developer
```

命令返回精确的 identity_file 路径，位于 `.aipipe/.runtime/agents/<UUID>.json`；下文 `ACTOR.json` 代指该实际路径。文件只含非秘密执行参数并由既有 .gitignore 忽略，不存 token、私钥或业务状态。配置中的仓库缺省时可从实际 GitHub origin 定位；命令不读取角色凭据。

| 工作角色 | credential-role | 记录位置 |
|---|---|---|
| developer | developer | commit、PR |
| reviewer | delivery | SHA 绑定的 Review、合并说明 |
| planner | delivery | 设计文档署名、发布的 Issue / Milestone、放行记录 |
| maintainer | 当前明确授权的 developer / delivery / owner | 维护提交、相关 Issue/PR 或配置交接记录 |

工作角色不是新的权限；Owner 模式只声明已授权维护身份，现有角色执行器不会因此提供 Owner token 或提升权限。规划、初始化和配置维护的本地文档可用 `identity show --identity ACTOR.json --operation planning` 或 `--operation initialization` 生成身份段落，随正式文档/交接记录提交。查询、help 和每次测试进程不额外向 GitHub 发评论。

## 提交与发布 PR

```bash
# 审查并显式 git add 本次文件，正文文件位于 .aipipe/.runtime/
aipipe commit --identity ACTOR.json --issue 1 --message-file .aipipe/.runtime/commit.md
aipipe push --role developer --identity ACTOR.json aipipe/issue-1
aipipe github --role developer --identity ACTOR.json -- pr create --base main --head aipipe/issue-1 --title '实现 Issue #1' --body-file .aipipe/.runtime/pr.md
```

Author 默认取当前身份。代提交已核实的另一 Agent 成果使用 `--author-identity WRITER.json`，共同作者用可重复的 `--coauthor-identity HELPER.json`。不为了修复历史署名创造来源不明的身份。此命令只处理普通新提交；cherry-pick/rebase/merge 中暂停该入口，使用保留原作者的 Git 流程，不自动归到当前 Agent。

PR 正文仍须按模板填写真实实现、测试、SHA、未完成项及返修轮次，并包含 Closes #N。CLI 自动追加可见的执行身份段落；编辑 PR 时保留此前有效身份段落。不要把同一人的多次更新当作不同模型独立验收，也不要手工破坏段落边界。

## 独立验收与合并

验收者新建 reviewer / delivery 身份，先 `doctor --for review`。在干净检出中验收当前 PR；运行产品代码时不注入写凭据。报告使用实际结果及可复现问题，不以 CI 绿色代替检查。

```bash
aipipe github --role delivery --identity REVIEWER.json -- pr review 6 --request-changes --match-head-commit FULL_SHA --body-file .aipipe/.runtime/review.md
# 全部满足时将 --request-changes 改成 --approve
aipipe github --result-json --role delivery --identity REVIEWER.json -- pr review 6 --approve --match-head-commit FULL_SHA --body-file .aipipe/.runtime/review.md
```

`--match-head-commit` 是 aipipe 对 attributed review 的扩展：先核对当前 head，再通过 REST commit_id 绑定 Review，并回读检查 head 是否改变。新提交必须重新验收。角色与 identity 不匹配时在读取凭据前停止。

批准及原生必需检查通过后，使用 SHA 限定的即时 squash 合并：

```bash
aipipe github --role delivery --identity REVIEWER.json -- pr merge 6 --squash --match-head-commit FULL_SHA --body-file .aipipe/.runtime/merge.md
aipipe github --result-json --role delivery --identity REVIEWER.json -- pr merge 6 --squash --match-head-commit FULL_SHA --body-file .aipipe/.runtime/merge.md
```

带身份的合并目前只支持该路径，不接受 auto 或 admin。等待 CI/审批由操作者按 Skill 完成；不为身份记录另造调度器。CLI 把原 PR/提交的作者与 trailers 汇入 squash 正文，记录合并处理人及原 head；列表不完整时停止，CLI 直接调用普通 GitHub PUT merge，由服务端在写入时核对 head 与保护规则，并回读 merged、合并 SHA 与原 head；不使用 gh 的合并前置策略判断。随后回读 MERGED、实际主分支检查与开发分支删除；仓库已开启合并后删分支。平台生成的 author/committer 不改写，完整来源保存在 PR、Review 与 squash 正文。

0.5.3 修正同步合并接口的写入拒绝分类：HTTP 403/404/405/409/422 返回 `primary.status=failed`、`github_rejected`、退出码 1；405 表示本次不能合并，409 表示请求 SHA 与实际 head 不符。它们不触发 metadata，也不自动重试。其他无法确认的写入（网络、超时、5xx 等）和已写成功后的回读失败继续返回 `unknown`、退出码 2，只提供只读核实路径。参见 [GitHub 同步合并契约](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request)。

`--result-json` 只改变结果报告，不改变 Review/merge 的身份、SHA 绑定或保护规则。JSON 中 `primary.status=succeeded` 只表示主 Review/merge 已确认，不表示 metadata 或完整业务交付都完成；metadata 失败时按输出的 `aipipe metadata` argv 修复，不能重复原 Review/merge。`primary.status=unknown` 表示写入可能已经发生但无法确认，只能按输出的只读 argv 核对 PR/Review 事实。

## 规划发布、放行与其他处理

- `publish --identity PLANNER.json --plan FILE --design-ref SHA --apply` 自动记录新 Issue 与 Milestone 的发布人；再次运行不改写原记录。批次契约比较只剥离格式有效的尾部身份段落，业务正文变更仍会阻断。
- `release --identity PLANNER.json --milestone N --plan FILE --design-ref SHA --apply` 核对原契约后保留既有发布人并追加放行人。默认仍只读。
- `api --identity FILE --role ROLE PATH` 对 body/description 写入附记录；Issue、PR、Milestone 状态 PATCH 保留旧正文与身份。Review API 同样须提交当前 commit_id；合并使用上述专用 gh 入口。
- issue/pr 的 close、reopen 记录在该操作的 comment；辅助标签、分支删除等无正文接口沿用 GitHub 实际账号，并在所属 PR 的交接/合并记录关联处理人。Owner 的 App/凭据初始化由初始化 Skill 将 identity show 段落写入非秘密交接记录，不写出凭据本身。

## 既有项目启用与边界

旧配置保持兼容；升级项目在完成资源同步后设置：

```json
{
  "compatibility": {"minimum_cli_version": "0.4.1"},
  "attribution": {"required": true, "legacy_before": "启用前已核实的完整提交SHA"}
}
```

required 要求角色写操作显式携带身份；push 使用当前角色凭据读取实际远端默认分支 SHA 并获取其历史，检查 HEAD 中尚未进入该主分支的新提交是否有一致的作者与 trailers，不依赖本地 origin/main 是否更新。legacy_before 仅在仍为 HEAD 祖先时豁免启用前历史；squash 后失去祖先关系的旧基线不再豁免任何新提交，已合并历史由远端主分支边界识别。主分支尚不存在时检查全部非豁免历史。远端读取/获取失败、无共同历史或浅克隆均停止推送；不重置基线、不关闭 required。该规则是 CLI 防误操作措施；Git 和本地配置可被操作者直接修改，不是不可伪造的模型审计机制。

本地身份文件只是执行参数，完成事实留在 GitHub。续接直接从 PR/Review 读取前任身份并生成自己的新身份；新版本必须同步当前测试项目、通过验证并推送后再交付。
