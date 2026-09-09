---
name: aipipe-publish
description: 将已有开发切片计划预览并批量发布为 GitHub Milestone 与 Issue，或续接未完成的发布。不要求重新设计开发方案，任何用户选择的 AI 开发工具均可调用。
---

# 发布已有切片

读取 [共同约定](../../AGENTS.md) 和 [配置执行说明](../../references/configuration.md)。本 Skill 处理已经准备好的切片，不自动重写方案或重新拆任务。

1. 确认目标仓库、已有计划、设计文件的已提交版本、批次和用户授权。复用已有 Issue 时直接处理它们，不运行发布器重新创建。
2. 读取 [批次示例](../../plans/batch.example.json) 和 [Issue 模板](../../templates/issue.md)，核对依赖、范围、验收、测试和交付物。缺少必要信息只补具体缺口；可以引用已有设计位置，不强制生成新开发文档。
3. 离线预览：`aipipe publish --plan .aipipe/plans/batch.json --design-ref COMMIT_SHA`。
4. 已授权发布时，加 `--apply`。执行器从项目配置确定仓库和 Delivery 凭据引用，从仓库外读取该角色 token，不回退到个人 gh 登录。没有 Git origin 的草稿可预览，远端写入前完成仓库绑定核对。
5. 出现重复标记、内容冲突或结果不明时停止写入，检查 GitHub 的实际结果；允许复用完全一致的已发布项，不能盲目重试 POST。每批同时只运行一个发布者。
6. 发布后核对真实 Issue 编号、Milestone 和依赖，已授权交接开发时由初始化宿主运行 `aipipe release --milestone N --plan FILE --design-ref SHA --apply`，交接检查通过才放行；发布成功本身不代表初始化完成。不启动客户端、不建立任务数据库。

批次需要修改时，未开发任务经明确评估后在 GitHub 修订；不能修改本地 JSON 后指望发布器自动覆盖已开发 Issue。设计输入不足时可按需调用 `aipipe-plan`，不是发布的固定前置。

正式发布前确认设计和计划已推送到 GitHub，可由其他工具按版本读取；设计链接不能依赖私人笔记或临时目录。只预览不要求推送；已有任务不重新发布。定稿后的来源规则见[文档与账本](../../references/documentation.md)。

## 实际执行身份

发生写入前读取 [身份记录](../../references/identity.md)，创建本会话身份（工作角色 / 凭据角色：planner / delivery），实际模型不可确认时写 unknown。提交代码时用 `aipipe commit`；相关角色写命令传 `--identity FILE`。不沿用其他工具的 Agent ID，不把人类宿主名当代码作者；恢复操作保留前任作者与交接记录。只读操作不强制创建身份。

## 阶段与元数据

读取 [元数据约定](../../references/metadata.md)。业务切片继续由 publish 创建 ready 与指定 milestone；维护任务也应有阶段标签与独立维护 milestone，不加入业务批次。标签 ready 不等于已放行或依赖已完成。
