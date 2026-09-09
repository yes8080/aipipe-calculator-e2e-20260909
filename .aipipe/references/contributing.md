# aipipe 维护与开发说明

## 范围与结构

aipipe 提供可移除的 Skills、JSON 项目配置、配置生成与执行工具，以及面向人的使用文档。不实现模型路由、客户端启动器、常驻服务、任务数据库或新的合并平台。

设计原则：gh 已有的能力直接复用，优先使用原生命令、JSON 输出和 body-file；仅在原生命令不能满足明确契约时使用 `gh api`。aipipe 只补必要的配置、身份、脱敏和结果判断，不重复实现分页、缓存、队列或 GitHub 状态管理。

`AGENTS.md` 维护共同约定；`skills/` 为六个能力入口；`references/` 为人读文档；`src/aipipe/` 为唯一 Python 实现；`scripts/` 只保留四个旧命令的兼容包装。`pyproject.toml` 生成 wheel 和 console entry point，打包时直接纳入原有 Skill、模板和参考文档，不维护第二份资源源码。

- `context`、`config`：发现目标项目，合并与验证非秘密配置。
- `credentials`、`github`：仓库外角色凭据、隔离环境、gh 传输和错误脱敏。
- `initialize`、`manifest`、`owner_auth`：按需接入、一次性注册回调、Owner 签发和保存凭据。
- `policy`、`compatibility`：只读核验现有保护、多个检查和版本契约；不迁移原规则或覆盖资源。
- `readiness`：角色/门禁只读检查与既有批次放行，开发和验收接收端不读取另一角色凭据。
- `runner`、`publish`：执行原生命令、角色 GitHub 操作、批次预览与可恢复发布。
- `cli`：统一参数路由；命令不依赖安装目录作为目标项目。

Python 3.9+，运行时使用标准库；构建使用 Hatchling。需要 GitHub 操作时用 `gh`，JWT 签名用 `openssl`。本地测试不访问 GitHub，其中一次性回调测试需要本机 loopback socket 权限。

## 修改与验证

```bash
python3 -m pip install .aipipe
AIPIPE_TEST_BINARY="$(command -v aipipe)" python3 -m unittest discover -s .aipipe/tests -v
git diff --check
```

未设置 `AIPIPE_TEST_BINARY` 时安装产物测试明确跳过；发布验证与 GitHub CI 必须设置它，验证已安装入口可从其他项目运行。

测试应验证用户可见行为：传统项目原生命令是否执行；默认预览是否不触网；失败写是否不重复；不同角色是否取得各自凭据；本地测试是否不携带声明的写 token；目标仓库错误时是否停止。不要用匹配文案替代行为测试。

Skill 更新后检查 YAML frontmatter、相对引用、输入/输出和停止条件。支持既有配置时保留未涉及字段；需要不兼容迁移时显式改变 schema_version 并提供迁移说明，不能静默重置 App 或 CI。执行用户配置意味着执行代码，评审新增参数和命令边界。

## 交付边界

模板 CI 的 `aipipe-template-checks` 只证明工具测试通过。实际 App 注册、安装、Review 计入批准、GitHub 规则阻拦、自动合并和删除分支必须在获授权的真实仓库测试。离线 mock 或配置成功不能替代这些证据。

新增配置能力必须同时补可读使用说明、Skill 调用位置及行为测试。所有 aipipe 自有文件保持在 `.aipipe/`；新增工作流采用 `.github/workflows/aipipe-*.yml`。不要为原生自动发现将相同规则复制到多个仓库目录。

接手先 `aipipe inspect`：cli 字段报告真实入口、源码位置、运行版本、项目资源版本、内置源码版本与兼容性。新资源包含 `.aipipe/compatibility.json`；项目也可用 `config set --minimum-cli-version 0.3.0` 登记最低版本，两者取更严格值。版本不足时，在原生命令或角色凭据读取前停止；inspect/doctor 保留诊断结果。旧资源没有版本标记时显示未知，不自动标成新版。

升级使用已核实入口对应的安装环境，审查 Skills、project.json、plans 与定制差异；不覆盖用户内容。旧于 0.3.0 的 CLI 尚不识别该契约，接收者必须先自行核对 `--version` 并升级；不能声称新代码可以约束尚未更新的旧二进制。不会为了版本探测启动外部开发工具。

`identity` 负责声明代码作者与实际处理人；它不是认证源。普通开发提交使用 aipipe commit，维护也记录实际身份。身份功能的测试须覆盖本机 Git 配置不变、无写凭据的提交进程、角色与仓库不匹配、发布幂等、当前 SHA Review 和 squash 作者保留。新版本同轮同步测试项目。

## 任务元数据

阶段、PR 标签及 Issue 里程碑约定、Owner 工作流安装及手工修复见 [元数据约定](metadata.md)。新版本须同轮同步模板、全局 CLI、测试项目及生成的自动化文件。
