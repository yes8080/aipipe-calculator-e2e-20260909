# 项目配置与执行入口

本文件面向使用 aipipe 的开发者和 AI 工具。项目配置是可执行命令及 GitHub 绑定的来源，执行前应审阅配置中的命令；不把外部 PR 修改过的配置直接带入 Owner 凭据环境运行。

## 三类数据分别保存

| 数据 | 保存位置 | 是否入 Git |
|---|---|---|
| 仓库、分支、App/Installation ID、逻辑凭据引用、命令与用户偏好 | `.aipipe/project.json` | 是 |
| 本机逻辑引用到环境变量 / token 文件的映射 | 默认 `~/.config/aipipe/credentials.json` | 否 |
| App 私钥、临时 token | Owner 安全存储或受权限限制的外部文件；开发宿主只取得自己的 token | 否 |
| Issue 进度、PR、验收、CI 和合并结果 | GitHub | 不另建本地任务数据库 |

## 项目配置示例

```json
{
  "schema_version": 1,
  "repository": "OWNER/REPO",
  "default_branch": "develop",
  "apps": {
    "developer": {"app_id": 1001, "installation_id": 2001, "slug": "owner-dev", "credential_ref": "acme/orders/developer"},
    "delivery": {"app_id": 1002, "installation_id": 2002, "slug": "owner-delivery", "credential_ref": "acme/orders/delivery"}
  },
  "ci": {"required_check": "build", "workflow_path": ".github/workflows/build.yml"},
  "metadata": {"mode": "inline"},
  "commands": {
    "backend.verify": {"cwd": "backend", "argv": ["./mvnw", "-B", "verify"]},
    "frontend.test": {"cwd": "frontend", "argv": ["npm", "run", "test:unit"]}
  },
  "preferences": {
    "planning": {"tool": null, "model": null},
    "development": {"tool": null, "model": null},
    "review": {"tool": null, "model": null}
  },
  "execution": {"strip_env": ["CUSTOM_GITHUB_WRITE_TOKEN"]}
}
```

上述路径和命令必须根据实际项目确认。`commands` 只引用业务原生入口，原生脚本与 CI 不反向调用 aipipe。`preferences` 可按用户选择填写工具/模型名字，也可保持空值；不会触发模型或客户端调用。

初始化 Skill 可以直接生成可审查的 JSON，也可用 `aipipe config set`：按角色传入实际 App/安装编号，`--commands-file FILE` 合并命令对象，`--preferences-file FILE` 合并用户偏好。命令对象为上例 `commands` 的内容，不是整个 project.json。仓库改绑必须显式 `--rebind`，这会清除旧仓库的 App 安装、默认分支和 CI 绑定；命令与业务偏好仍须核对适用性。

字段未配置时，仅对应操作不可用。例如 commands 为空不能执行某个产品检查，但不阻止读取代码；repository 为空可本地配置和检查，不能调用 GitHub。保留已有默认分支和检查名，模板的空配置不能被当作已初始化。

`metadata.mode` 是非秘密运行配置，取值为 `inline` 或 `workflow`，缺省等同 `inline`。`workflow` 只表示项目选择由可信默认分支 GitHub Actions 同步元数据；它不是本地运行状态，也不证明工作流已部署。Owner 启用前必须在 GitHub Issue/PR 留下真实默认分支验证证据。

## 命令登记与修复

`commands` 的值必须是 `{cwd, argv}` 对象，不能直接复制 package.json 的 shell 字符串。命令键只允许字母、数字、`_`、`.`、`-`；npm 的 `test:e2e` 是 argv 参数，可以使用 `e2e` 作为 aipipe 命令键：

```json
{
  "test": {"cwd": ".", "argv": ["npm", "run", "test", "--", "--run"]},
  "typecheck": {"cwd": ".", "argv": ["npm", "run", "typecheck"]},
  "build": {"cwd": ".", "argv": ["npm", "run", "build"]},
  "e2e": {"cwd": ".", "argv": ["npm", "run", "test:e2e"]}
}
```

将这个命令对象保存为临时 JSON 后执行 `aipipe config set --commands-file FILE`，再运行 `aipipe config validate` 与对应 `aipipe run NAME`。set 合并同名项而不删除旧项；若已经写入 `test:e2e` 等非法键，需在 project.json 中移除该旧键并登记合法键，保留其他配置。

CLI 0.3.1 的配置错误指出文件和 `commands["名称"]` 字段。旧版的 `invalid configured command` 也是配置错误：inspect 不读 token，因此 inspect 同样失败时不要将其归因于 App 未安装或凭据过期。配置修复后再运行角色 doctor；如果此时另有凭据错误，再按真实证据处理。CLI 不自动把字符串转成 shell 命令，也不静默跳过损坏配置。

## 仓库外凭据登记

由用户或已授权的初始化工具在相应宿主建立 registry，JSON 只含映射，不含 token 内容。POSIX 环境建议外部目录权限 `0700`、文件 `0600`。

```json
{
  "credentials": {
    "acme/orders/developer": {
      "kind": "token_file",
      "path": "/absolute/developer-only/orders.token"
    },
    "acme/orders/delivery": {
      "kind": "env",
      "name": "AIPIPE_ORDERS_DELIVERY_TOKEN"
    }
  }
}
```

开发宿主实际只配置 developer 项，验收宿主只配置 delivery 项；表中合写是为了说明两种格式。可增加 `expires_at` 的 ISO 8601 带时区时间，执行器会在过期时停止认证动作。重新签发后同步更新文件和该时间；没有填写时间时由 GitHub 判断有效期，认证失败不自动重试写入。

优先让宿主从已有系统凭据管理能力注入 `AIPIPE_...` 环境变量；执行器不内置系统钥匙串适配器。使用文件时保存 installation token 本身，禁止保存 App 私钥。registry 和 token 文件都不能位于项目检出中。

`aipipe auth issue-token` 由 Owner 从可信版本在受信任环境执行，使用项目外 PEM 签发限一个仓库的角色 token，写外部 `0600` 文件并报告到期时间。配置模式会同时更新外部 registry 与 `credential_ref` 的 token 映射。私钥无需传给开发工具；同账号全文件访问不构成隔离，需宿主权限、独立账号或容器边界。App 创建、安装与签发步骤见 [App 指南](github-apps.md)。

## 任意 AI 工具的相同调用方式

当前执行器面向 github.com，GitHub Enterprise host 尚未实现；不静默把企业仓库请求发往公共 GitHub。执行器只需要 Python 3.9+；远端调用使用已安装的 `gh`，推送还使用 `git`。不需要安装或启动某个模型客户端。

```bash
# 只读本地配置，不读取 token，不访问网络
aipipe inspect

# 运行配置中的原生检查，无 GitHub 写凭据
aipipe run backend.verify

# 只读读取交接状态（角色 token 仅注入这次 status 读取）
aipipe status --issue 42 --role developer --json

# 读取 Issue（角色 token 仅注入这次 gh 子进程）
aipipe github --role developer -- issue view 42

# 根据实际配置创建 PR，正文直接包含 Closes #42
aipipe github --role developer -- pr create --base develop --head aipipe/issue-42 --body-file .aipipe/.runtime/pr.md

# 使用 App 身份推送明确分支，origin 必须为当前仓库 HTTPS URL
aipipe push --role developer aipipe/issue-42

# 验收当前 SHA 后提交批准并请求原生合并；结构化入口把主操作和 metadata 结果分开
aipipe github --result-json --role delivery --identity REVIEWER.json -- pr review 57 --approve --match-head-commit FULL_SHA --body-file .aipipe/.runtime/review.md
aipipe github --result-json --role delivery --identity REVIEWER.json -- pr merge 57 --squash --match-head-commit FULL_SHA --body-file .aipipe/.runtime/merge.md

# REST 相对路径始终位于配置的仓库之下
aipipe api --role delivery milestones --method GET

# 离线预览；获授权后加 --apply，执行器读取 Delivery 映射
aipipe publish --plan .aipipe/plans/batch.json --design-ref COMMIT_SHA
```

先准备正文文件并填真实参数。全局参数 `--config PATH`、`--credentials PATH` 写在子命令之前。指定配置时项目根目录取该配置所在 `.aipipe/` 的父目录；因此可从已安装的可信脚本操作另一个已经接入的项目。

`status` 的详细字段、Review/checks/head 语义和 unknown 边界见 [status 只读交接状态](status.md)。

认证动作先核对 Git origin 与配置中的仓库，缺失或不一致时停止。只解析本次角色的 `credential_ref`，不回退个人 gh 登录；App token 权限和 GitHub 分支规则仍是远端强制边界，执行器不是新的权限服务器。[gh 环境变量](https://cli.github.com/manual/gh_help_environment)

`--result-json` 是 aipipe 自身参数，必须放在 `--` 前，避免与传给 gh 的 `--json` 混淆。该模式当前只支持带 `--identity FILE` 的 `pr review` 和 `pr merge`；不支持的操作、缺少身份、无效参数和写前读取失败在凭据读取或主写入前失败。写入后响应缺失、超时、5xx、回读失败、回读不一致或 head 变化均报告 `primary.status=unknown`，恢复命令只做只读核对，不自动重复 Review/merge。

业务命令用参数数组直接执行，不拼接 shell；需要管道时将逻辑放回项目原生脚本。`run` 清除 GH_TOKEN/GITHUB_TOKEN 等 GitHub token、所有 AIPIPE_ 前缀环境变量及 `execution.strip_env` 指定变量。这不是操作系统沙箱，项目目录外的文件访问仍由宿主控制。

## 故障处理

缺少命令就回到初始化登记该命令；缺少 registry 映射就在当前宿主补映射；token 失效只补签发，不重建 App；origin 不匹配先确认 checkout，不自动改远端。子命令失败传播原退出码，执行器不循环、不重试 POST、不启动下一个模型会话。

共享 App：同 Owner 且权限恰好匹配角色时沿用默认接入。跨 Owner 或权限更宽的已有 App，先绑定明确的 App ID；Owner 用 `auth trust-app --role ROLE --app-owner OWNER --permissions-file FILE` 读取真实 App 并预览，再按授权加 `--apply`。FILE 是完整非秘密 App permissions 对象，必须与实际值一致并足以提供当前角色。该命令不修改 App 权限、不安装仓库、不签发 token。

信任记录保存在仓库外 `owner/trust/OWNER/REPO/ROLE.json`，绑定仓库、角色、App ID、Owner 和完整权限，0600；项目配置不能自我授权。身份/权限漂移时停止重授权。后续签发只申请当前仓库及固定角色权限，并核对返回的 token 权限后保存；共享 App 的额外权限不传给角色 token。组织安装审批/SSO 仍需账号方完成，不能把离线测试写成真实组织已验证。

实际执行身份与项目偏好分开：preferences 只表示选择意向；工具/模型/工作角色/Agent ID 记录在本会话身份及 GitHub 产物。`attribution.required` 和 `legacy_before` 的迁移约定见 [身份指南](identity.md)。
