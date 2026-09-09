# 内测自动缺陷上报

0.5.3 增加项目配置 `error_reporting`。默认关闭；只有目标项目明确开启且能读取指定上报凭据时才向固定仓库 `yes8080/aipipe-template` 创建 Issue。不使用当前项目的角色配置推断上报身份，也不回退 Owner 的 gh 登录。

```json
{
  "error_reporting": {
    "enabled": true,
    "credential_ref": "aipipe/central-error-reporter"
  }
}
```

启用前，Owner 在仓库外 credential registry 中登记该引用。凭据应只有目标仓库的 Issues 读写权限；可引用已授权给目标仓库的短期 App token，不扩展业务项目的 Developer 权限，不在此命令中自动签发或刷新凭据。

```json
{
  "credentials": {
    "aipipe/central-error-reporter": {
      "kind": "token_file",
      "path": "/outside-project/reporter.token",
      "expires_at": "<实际过期时间>"
    }
  }
}
```

文件位于仓库外，权限 0600；使用环境变量入口时使用 `AIPIPE_` 前缀，避免传入产品检查进程。

```bash
aipipe config set --auto-report-errors on --report-credential-ref aipipe/central-error-reporter
aipipe config set --auto-report-errors off
aipipe inspect
```

启用命令只修改配置，不立即发送 Issue，并将项目最低 CLI 版本至少提高到 0.5.3（不降低已有更高要求）；关闭后不读取上报凭据、不访问上报仓库。`inspect` 显示当前配置。无效配置不能构成上传授权。

## 哪些内容会发送

仅发送 CLI 版本、顶级动作类型、最多 5 个去重错误的固定分类、HTTP 状态、请求方法、遮蔽路径值并移除查询参数的 API 路由，以及 aipipe 内部模块名/行号。报告不包含项目名、用户目录、命令参数、Issue/PR 正文、错误消息、原始 stdout/stderr、请求/响应正文、环境变量、token、私钥或 credential registry。

同一版本、动作和脱敏错误生成固定 fingerprint；直接使用 `gh issue list --state all --limit 500 --json number,body` 查询，已有同标记的开放或关闭 Issue 时复用，不追加重复评论；创建使用 `gh issue create --body-file`。分页交给 gh，不实现本地报告数据库或队列。列表可见性延迟和并发创建仍可能造成重复，不声称原子去重。查询失败或结果达到 500 条且未找到匹配时停止上报，不盲目创建。

自动报告只是待维护者判断的诊断线索，权限拒绝或网络错误不自动认定为 aipipe 缺陷。维护者核实后再归入正式维护任务。需要深入诊断时，在相应 Issue 补充版本、脱敏复现步骤和公开 CI 链接；不要追加未审查的原始日志。

## 触发与失败边界

捕获 CLI 异常、联网 doctor 检查错误、结构化 Review/merge 的 preflight/write/readback/metadata 错误，以及 github/api/push 子进程的非零退出（只记录 process 类型，不读取其输出）。`run` 的业务测试失败、只读 `status`、`inspect`、配置/凭据/身份命令、所有显式 `--offline`、init/publish/release/metadata 的非 apply 模式不触发上报。其他没有捕获错误的普通非零返回值不自动推断为工具缺陷。

报告独立执行，保持原命令的退出码和 stdout；通知只写 stderr。上报 gh 子进程单次超时 5 秒，不自动重试写入；缺少/过期/权限不足的上报凭据、查询失败、创建响应不确定都仅输出固定上报不可用提示，不能递归上报自己。上报失败不重跑原命令、不索取更多权限，也不影响已确认的 Review/merge。
