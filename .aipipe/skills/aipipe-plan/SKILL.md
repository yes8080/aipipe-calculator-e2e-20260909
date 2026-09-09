---
name: aipipe-plan
description: 根据项目需求、docs、现有代码或 Issue 生成可开发的方案，编排里程碑和带测试要求的切片，并在授权范围内批量发布 GitHub Issue。可独立用于新项目或已有项目。
---

# 规划与批量发布

读取 [公共入口](../../AGENTS.md)。规划本身不需要 GitHub App；只有远端发布操作需要相应身份。

用户选择任何支持文件读写的 AI 开发工具与模型来执行本 Skill，包括 ZCode、OpenCode、Claude Code 或 Codex；aipipe 不指定规划必须由 GPT-6 完成，也不调用模型 API。先明确本次只要开发文档、只要切片，还是完整规划；只生成用户需要的产物。

只设计文档时，完成后结束；已有方案只需拆片时，复用原方案；已有切片只需发布时，直接调用 [aipipe-publish](../aipipe-publish/SKILL.md)，不重新设计。传统项目接入初始化也不隐含调用本 Skill。

初期产品构思可来自个人笔记；定稿后将正式方案、必要附件与发布计划保存到 GitHub 仓库，后续只修改正式版本。执行交接不得依赖 Obsidian 或原聊天。迁移与版本引用见[文档与账本](../../references/documentation.md)。离线只设计仍可独立执行，不隐含远端发布。

## 选择实际输入与产出

1. 使用用户指定的文档、现有架构、Issue 或会话需求。新模板项目优先读取根目录 `docs/`；已有项目沿用当前文档，不要求先搬迁或重新初始化。
2. 梳理目标、现有实现、模块边界、接口、数据模型、错误行为、迁移兼容和测试环境。先解决会影响实现方向的缺口，其余写明假设并继续可独立推进的设计。
3. 输出或更新产品开发文档，缺少既有路径时使用 `docs/development.md`。方案须具体到开发者能够实现和验证，不能只罗列技术名词。供开发使用的产品文档随产品保留。
4. 对近期范围按模块编排里程碑，再按可验收业务行为切片。记录依赖、交付范围、验收条件、对应测试、执行目录与命令。每个切片同 PR 交付实现和测试；不要把整个前端或整个后端作为一片。已有 Issue 足够时复用，不重新批量创建。

## 需要批量发布时

参照 [计划格式示例](../../plans/batch.example.json) 与 [Issue 模板](../../templates/issue.md)，在 `.aipipe/plans/` 写本批 JSON。示例中的业务仅解释格式，不得原样发布到用户项目。一个计划对应一个里程碑，多里程碑逐个发布。正式执行交给独立 `aipipe-publish`；用户只要求生成计划时不写 GitHub。

先将正式开发文档提交到目标仓库的可访问分支，记录实际 commit SHA；已有项目遵循原 PR 流程。远端 Issue 引用该不可变版本，不能链接只存在本地的文档。

```bash
aipipe publish --plan .aipipe/plans/batch.json --design-ref COMMIT_SHA
```

默认离线预览，不写 GitHub。检查实际范围、测试和依赖后，若用户已授权发布，用外部注入的 Delivery token 加 `--apply`。发布脚本只发布这一批，不启动开发工具或自动放行批次。

同一批只运行一个发布者。失败后先核对 GitHub 中已有 Milestone 和 Issue，再重试；遇到同一切片重复或内容冲突，停止该批写入并处理冲突，不重建新批次掩盖结果。

发布完成后在 GitHub 核对实际编号、里程碑及依赖。按用户授权在初始化宿主执行 `aipipe release --milestone N --plan FILE --design-ref SHA --apply`；先通过交接检查，再放行。失败时保留已发布 Issues 并补齐具体缺项，不以“用户会手工启动工具”作为忽略 App、凭据或门禁的理由。业务代码与测试仍由开发片实现。

提供仓库、Issue 顺序、开发入口与验收入口。用户手工启动相应工具；规划 Skill 不启动任何开发客户端。

## 实际执行身份

发生写入前读取 [身份记录](../../references/identity.md)，创建本会话身份（工作角色 / 凭据角色：planner / delivery），实际模型不可确认时写 unknown。提交代码时用 `aipipe commit`；相关角色写命令传 `--identity FILE`。不沿用其他工具的 Agent ID，不把人类宿主名当代码作者；恢复操作保留前任作者与交接记录。只读操作不强制创建身份。

## 阶段与元数据

读取 [元数据约定](../../references/metadata.md)。业务切片继续由 publish 创建 ready 与指定 milestone；维护任务也应有阶段标签与独立维护 milestone，不加入业务批次。标签 ready 不等于已放行或依赖已完成。
