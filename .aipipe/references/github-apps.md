# GitHub App 创建、调用与仓库设置

本指南供独立的 `aipipe-init` Skill 按需使用：创建或复用 GitHub App、安装到选定仓库、登记项目配置，或者单独补齐 CI 与规则。Developer 负责开发与 PR，Delivery 负责发布任务、验收和合并。App 只提供身份和权限；领取循环由现有宿主运行，不需要 webhook 服务。本模板不表示你的 GitHub 账号已完成以下配置。

传统项目首次接入要生成项目配置、复用现有能力并接入所需身份，不生成开发方案。已经使用 aipipe 的项目仅补当前缺口。这不是所有任务必须依次完成的业务开发向导。接管已有项目时保留现有仓库、默认分支、CI、测试命令及已满足要求的保护规则；缺少某个 App 只阻止必须用该身份执行的 GitHub 动作，不阻止分析、规划或本地开发。

实测证据见 [初始化接口实测记录](initialization-validation.md)：两个 App 注册、单仓库安装、gh token 签发及真实 PR 交付已完成；CLI 0.2.0 已完成集成，并实测复用 App、刷新凭据和复用现有规则。

## 0. 先读取，再选择本次要补齐的内容

先读取目标项目的 `.aipipe/project.json`（如果存在），再检查 Git remote 和当前仓库事实：

```bash
git remote -v
gh repo view OWNER/REPO --json nameWithOwner,defaultBranchRef
gh workflow list --repo OWNER/REPO --all
gh api repos/OWNER/REPO/rulesets
```

只读检查可使用当前已有的有效身份，不要求事先创建 App。没有联网凭据时先读取本地配置、工作流与项目文件，明确哪些远端事实还没有验证。

| 本次需求 | 使用本指南的内容 |
|---|---|
| 只补 App 或安装 | 第 2–4 节；已有可用 App/安装直接复用 |
| 只登记或修正项目配置 | 下文配置命令；不重新创建 App |
| 只接入 CI | 第 5 节中 CI 部分；已有业务 CI 保留实际名字 |
| 只补主分支保护或角色写入资格 | 第 5 节对应规则；先读已有配置，只补缺项 |
| 完整接入新仓库 | 按实际依赖组合操作；首业务 PR 的检查可在合并前补验 |

中断后恢复同样先读配置和 GitHub：按已保存的 App ID/slug 找 App，按 Installation ID 与目标仓库确认安装，按名称和内容找已有 ruleset。App 创建成功但配置尚未落盘时先查 App 管理页面，找到了就记录，不再点一次 Create。已有安装只是漏选当前仓库时，修改该安装的仓库选择，不新建同角色 App。

项目配置仅保存非秘密静态信息。例如：

```json
{
  "repository": "OWNER/REPO",
  "default_branch": "main",
  "apps": {
    "developer": {
      "app_id": 123456,
      "slug": "owner-aipipe-developer",
      "installation_id": 234567,
      "credential_ref": "owner-store:aipipe/developer"
    }
  }
}
```

可以只登记一个已确认角色；未确认字段不编造。`credential_ref` 是 Owner 外部凭据管理入口的引用，不是 token、私钥或其编码。运行以下离线工具按角色合并更新配置；它不会创建 App 或安装：

```bash
aipipe config set \
  --repo OWNER/REPO \
  --default-branch main \
  --role developer \
  --app-id 123456 \
  --installation-id 234567 \
  --slug owner-aipipe-developer \
  --credential-ref owner-store:aipipe/developer
```

所有参数填读取到的实际值；已有项目可能使用 `master`、`develop` 等默认分支，不能强改为 `main`。Delivery 使用相同命令并替换角色及其编号。确认实际业务 CI 后，可同时传 `--check-name ACTUAL_CHECK_NAME --workflow-path .github/workflows/ACTUAL_FILE.yml`。未确定 CI 时保留相关字段为空，不用模板自检检查代替。

需要记录本次初始化的待办时，复用 GitHub 中现有的初始化 Issue；本次请求包含该记录操作且具备写入身份时才创建。只记录尚需核验的实际动作，例如首业务 PR 出现后确认 required check 来源。不要在 `project.json` 添加“已就绪”“待合并”等运行状态。

## 0.1 CLI 引导，优先使用 gh

初始化默认由工具完成配置工作：收集必要输入后，先用 `gh` 专用命令；没有专用命令时用 `gh api` 调 REST / GraphQL；只有接口不支持或确需账号授权时才打开对应网页。用户只补未知信息和完成必要授权，不承担复制编号、搬运 PEM、逐项勾选权限或配置规则的常规工作。

0.2.0 已提供 `aipipe init` 交互向导、manifest 回调和仓库外凭据保存。安装及可复制命令见 [CLI 使用指南](cli.md)。下表说明向导使用的 gh 能力与必须保留的网页步骤。

| 初始化内容 | 首选操作 | 身份或实际限制 |
|---|---|---|
| 登录、账号核实 | `gh auth status`、`gh api user`；缺登录时 `gh auth login --web` | Owner；登录、2FA 或 SSO 授权可能需要用户 |
| 仓库创建、模板生成、克隆 | `gh repo create`、`gh repo clone`、`gh repo view` | Owner；先读后建，明确账号、可见性和目标目录 |
| 自动合并与删分支 | `gh repo edit` | Owner 管理权限；已有设置按差异更新 |
| 质量与角色写入规则 | `gh api repos/OWNER/REPO/rulesets` 的 GET / POST / PUT | Owner；复用等效规则、保留组织规则，核实套餐支持 |
| App 注册 | 浏览器提交预配置 manifest，再由程序执行 conversion API | 必须经过 GitHub 注册页面；权限、名称和主页由工具预填 |
| App 身份与安装查询 | App JWT 下 `gh api app`、`gh api app/installations`、`gh api repos/OWNER/REPO/installation` | 本地签 JWT；gh 必须显式使用 Bearer 头，响应自动提取编号 |
| 已有安装增加仓库 | `gh api --method PUT user/installations/INSTALLATION_ID/repositories/REPOSITORY_ID` | 官方要求有 `repo` scope 的 classic PAT 且用户是仓库管理员；不假设普通 gh OAuth 登录可用 |
| 首次 App 安装、权限更新批准 | 打开具体 App 安装或授权页面，完成后 API 核实 | 需要对应账号授权；没有身份条件时只暂停该步 |
| installation token 签发 | App JWT 下调用 `POST /app/installations/ID/access_tokens`，明确仓库与角色权限 | 集成向导优先通过捕获输出的 `gh api` 执行；当前签发脚本使用标准库 HTTP |
| 凭据保存、配置回写 | 本地原子写入与既有配置工具 | 私钥、token 不输出；项目配置只写非秘密字段与凭据引用 |
| CI 核实 | `gh workflow list`、`gh run list/view`、`gh pr checks` | 工作流文件由 Owner 通过正常代码变更交付；保留真实测试入口 |

仓库创建、设置与 ruleset 的调用依据分别见 [gh repo create](https://cli.github.com/manual/gh_repo_create)、[gh repo edit](https://cli.github.com/manual/gh_repo_edit)、[Rulesets REST](https://docs.github.com/en/rest/repos/rules)。底层通用入口见 [gh api](https://cli.github.com/manual/gh_api)。[App JWT 接口](https://docs.github.com/en/rest/apps/apps)、[给安装增加仓库的身份限制](https://docs.github.com/en/rest/apps/installations#add-a-repository-to-an-app-installation)

### 交互与身份约定

`aipipe init` 允许选择新建、接入或修复，再按需执行 repo、apps、credentials、checks 子步骤；显式参数与交互输入使用同一实现。先读取项目和远端已有信息，仅问缺项。传统项目接入不生成开发方案，已有项目恢复不重复创建资源。

实测补充：关闭 Webhook 的 manifest 也必须提供 `hook_attributes.url`；仅有 active=false 会被 GitHub 拒绝。完整对象使用有效 URL、active=false 和 default_events=[]。

Owner 的 `gh` 登录用于仓库创建和管理设置；App JWT 用于 App 身份、安装查询与 token 签发；Developer / Delivery installation token 用于日常协作。CLI 逐个子进程提供正确身份，清除冲突认证变量，不用 `gh auth login` 把 App 身份写成用户的全局默认身份。两 App 不因初始化便利而新增 Administration 或 Workflows 权限。

`gh` 不负责本地 JWT 签名和安全落盘，这两项保留小型本地实现。通过 stdin 传 JSON 请求体，捕获含凭据的 API 响应，不启用认证调试日志，不将响应原文拼入错误消息。未持有合适 classic PAT 时，已有安装的仓库授权直接采用网页引导，不为减少一次网页操作强制用户新建长期 token。

网页引导停留在当前需要的注册或安装页面；Owner 完成后由 CLI 自动查询事实继续执行。manifest 临时回调只在初始化期间监听本机、校验 state、单次消费并限时退出，不是常驻 webhook 服务。无浏览器或远程机器提供明确的手工完成路径，不能承诺另一台机器的浏览器能访问本机回调。

成功写入后回读验证，返回具体账号、仓库、App / Installation ID、配置路径和未完成项。401 / 403 区分身份类型、权限、组织策略及套餐等原因；不把一次拒绝当成资源不存在，不自动扩大权限或重复创建。已获授权的动作连续执行；中断恢复核对 GitHub 事实和已登记对象。


## 1. 准备信息

本次需要创建 App 时，由仓库 Owner 准备：仓库 `OWNER/REPO`、实际默认分支、缺少角色的全局唯一 App 名称，以及项目目录之外的私钥和临时 token 存放目录。需要配置 rulesets 时，仓库须支持该能力；公开仓库可用 GitHub Free，私有仓库使用支持该能力的套餐。[Rulesets 可用范围](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)

建议名称为 `<owner>-aipipe-developer`、`<owner>-aipipe-delivery`。已有 App 时检查角色是否适合、安装仓库是否正确后复用；不为每个项目强制注册两套新 App。修改一个复用 App 的权限可能影响其其他安装，不能因为当前项目缺权限就静默扩大其他项目的权限。

## 2. App 注册与网页回退字段

仅为缺少且本次需要的角色执行本节。先查已登记 App 和 App 管理页面，确认没有可复用对象。使用已登录浏览器填写以下网页；登录、2FA、账号授权等必须由 Owner 完成的页面出现时，交给 Owner 完成，再从当前状态继续，不重新创建。用户已授权本次角色初始化时，按该范围完成创建、安装和登记，不反复询问同一事项。

个人仓库：头像 → **Settings → Developer settings → GitHub Apps → New GitHub App**。组织仓库在对应组织的设置中创建；选择实际拥有目标仓库的账号，避免私有 App 无法安装到另一账号。

两个 App 分别填写以下字段：

| 网页字段 | 设置 |
|---|---|
| GitHub App name | 对应角色的唯一名称，最多 34 个字符 |
| Description | `aipipe development agent` 或 `aipipe delivery agent` |
| Homepage URL | 仓库 URL 或 Owner 的 GitHub 主页 URL |
| Callback URL / Setup URL | 留空 |
| Request user authorization (OAuth) during installation | 不勾选 |
| Enable Device Flow | 不勾选 |
| Webhook → Active | **取消勾选**；不填写 Webhook URL、不订阅事件 |
| Where can this GitHub App be installed? | `Only on this account` |

本方案使用 installation token，不需要用户 OAuth 或持久化 Client Secret；manifest 初始化可使用一次性的本机回调。[注册 GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app)

交互向导以 manifest 为首选注册方式，上述完整网页字段保留为未集成 manifest、无可用回调或恢复密钥时的回退参考。0.2.0 已实现此握手；注册和安装仍需 Owner 在浏览器完成 GitHub 授权。官方流程为：浏览器 POST manifest 到个人或组织的 App 注册页，Owner 完成页面后，再用返回的临时代码调用 `POST /app-manifests/{code}/conversions` 交换配置。它仍含网页授权与一小时内完成的握手，CLI 应捕获响应并直接安全保存私钥，自动登记 App ID。[官方 manifest 注册流程](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest)

在 **Repository permissions** 中设置：

| 权限 | Developer App | Delivery App |
|---|---|---|
| Contents | Read and write | Read and write |
| Pull requests | Read and write | Read and write |
| Issues | Read-only | Read and write |
| Actions | Read-only | Read-only |
| Checks | Read-only | Read-only |
| Metadata | GitHub 自动提供 Read-only | GitHub 自动提供 Read-only |
| Workflows | No access | No access |
| Administration | No access | No access |
| Commit statuses | No access | No access |
| 其他仓库、账号、组织权限 | No access | No access |

点击 **Create GitHub App**。两个 App 均不获得创建检查结果、修改工作流或修改保护规则的权限。Delivery 的 Contents Write 用于合并，不代表验收测试进程应该直接编辑代码。[App 权限选择](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app)、[合并 API 权限](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request)

## 3. 安装与保存凭据

对每个 App 分别操作：

1. App 的 **General** 页面记录 **App ID**；不要使用 Client ID 替代本模板命令里的 `--app-id`。
2. 在 **Private keys** 区域点击 **Generate a private key**，将下载的 PEM 文件移到 Owner 管理的项目外目录，仅 Owner 可读取。两个 App 各用自己的私钥；不提交到 Git、不放进 `.aipipe/`，不作为 agent 工作目录中的文件。
3. 点击 **Install App**，选择目标账号，选择 **Only select repositories**，只勾选本次仓库后安装。
4. 记录本次 **Installation ID**。可从安装配置页面的数字 ID 获取；也可在 Owner 的 App JWT 身份下调用 `GET /repos/OWNER/REPO/installation` 获取 `.id`。App ID、Installation ID 是两种不同的编号。

记录表只保存编号与私钥位置，不保存私钥内容：

| 角色 | App ID | Installation ID | Owner 私钥文件绝对路径 |
|---|---|---|---|
| Developer | 待填写 | 待填写 | 待填写，必须在项目外 |
| Delivery | 待填写 | 待填写 | 待填写，必须在项目外 |

安装限定了 App 可以访问的仓库；签发 token 时还可进一步限定本次仓库。后续调整 App 权限后，Owner 必须在安装设置中接受更新，再签发新 token。[安装 App](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app)、[管理私钥](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps)、[查询仓库安装](https://docs.github.com/en/rest/apps/apps#get-a-repository-installation-for-the-authenticated-app)

## 4. Owner 签发短期角色 token

在项目根目录执行模板自带工具。先将示例数字、仓库名和绝对路径替换成实际值：

```bash
aipipe auth issue-token \
  --app-id 123456 \
  --installation-id 234567 \
  --private-key /absolute/owner-only/keys/developer.pem \
  --role developer \
  --repository REPO \
  --output /absolute/owner-only/tokens/developer.token

aipipe auth issue-token \
  --app-id 345678 \
  --installation-id 456789 \
  --private-key /absolute/owner-only/keys/delivery.pem \
  --role delivery \
  --repository REPO \
  --output /absolute/owner-only/tokens/delivery.token
```

工具由 Owner 运行，使用 Python 标准库与 `openssl` 签 JWT，再调用 `POST /app/installations/{installation_id}/access_tokens`。`--repository` 填仓库短名，不填 `OWNER/REPO`；Owner 已通过 Installation ID 选定账号。工具将 token 写到项目外的 `0600` 文件，只显示文件路径和过期时间，不向终端输出 token 内容。

installation token 有效期为 1 小时；仓库与权限不能超过 App 安装时授予的范围。到期后由 Owner 或其已有凭据入口重新签发，再注入后续任务。这里没有新增常驻凭据服务。[签发 installation token](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)

宿主只把本轮角色 token 注入对应进程的 `GH_TOKEN`。开发会话拿 Developer token，验收与合并会话拿 Delivery token；它们不拿私钥、不共享另一角色的 token。`--role delivery` 当前签发完整 Delivery 权限，不宣称已实现更细的阶段权限。

在已经完成角色 token 注入的进程中，可用以下只读命令确认安装可见仓库：

```bash
gh api installation/repositories --jq '.repositories[].full_name'
gh repo view OWNER/REPO --json nameWithOwner,defaultBranchRef
gh issue view ISSUE_NUMBER --repo OWNER/REPO
```

Git 推送采用 HTTPS，避免个人 SSH key 绕开 App 身份。角色会话可以逐次使用隔离的 credential helper，不修改用户全局 Git 配置：

```bash
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push origin HEAD
```

上述命令前，应已向当前进程注入对应 App 的 `GH_TOKEN`，并核对 origin 是目标仓库的 HTTPS 地址。不要把 token 拼进 remote URL。

在 POSIX 宿主中可以从角色 token 文件读取到环境，避免把内容打印到聊天或终端；例如先执行 `set +x`，再执行 `IFS= read -r GH_TOKEN < /absolute/role-only/token` 和 `export GH_TOKEN`。产品测试应在清除写凭据的环境中运行，例如 `env -u GH_TOKEN -u GITHUB_TOKEN ./mvnw -B verify`；JavaScript 项目同样使用已配置的原生命令。

项目外路径和 `0600` 用于防止误提交和其他账号读取，不能隔离同一操作系统账号下拥有全文件权限的 Agent。Owner 私钥应位于开发宿主不可访问的账号、容器挂载边界或已有凭据管理环境；只将短期角色 token 交给对应宿主。签发脚本从可信版本执行，不在待验收 PR 的测试进程中签发。安装 token 可用于 HTTP Git 访问；Contents Write 允许推送，但仍受仓库规则约束。[Installation 身份与 Git](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)、[gh auth setup-git](https://cli.github.com/manual/gh_auth_setup-git)

## 5. Owner 初始化仓库

本节只处理用户本次要求补齐的 CI 或规则。已有项目先保留其可用设置；以下 `main` 和 `ci` 是新项目示例，实际操作分别替换为真实默认分支和业务检查名。两个 App 没有 Workflows Write，首次安装和后续修改 `.github/workflows/` 由 Owner 处理。

没有业务代码的空模板尚不具备业务测试。仓库模板自检 `aipipe-template-checks` 只验证模板本身，不能作为业务 `ci` 门禁，也不为完成初始化编造一个必过测试。可以先创建 App、登记仓库和配置已知规则，继续规划、开发首个 Issue；首个业务 PR 产生后再核验真实测试、检查名称和来源。

如果本次需要新建业务 CI，在 `.github/workflows/aipipe-ci.yml` 中使用工作流名 `aipipe CI`、job/check `ci`，直接运行项目真实测试与构建命令，并替换不再需要的模板自检工作流。已有业务 CI 可保持原文件与检查名称；只有新增的 aipipe 专用工作流文件要求 `aipipe-` 前缀。

required check 可通过 ruleset API 预置为计划中的真实 context，即使还没有成功结果也保持等待；它不会让未检查代码获准合并。若网页必须先出现检查才能选择，等首个业务 PR 产生检查后由 Owner 完成选择。**Delivery 只能在 Owner 确认 required CI 与独立 Review 规则已实际生效后执行合并；这项合并前核验不阻止规划和首 Issue 开发。** 尚未绑定来源等缺项在初始化 Issue 中列为“合并前待核验”，不降级主分支规则来让 App 先合并。

在 Owner 身份下先读取仓库设置，仅为缺项执行：

```bash
gh repo edit OWNER/REPO --enable-squash-merge --enable-auto-merge --delete-branch-on-merge
gh api repos/OWNER/REPO --jq '{allow_squash_merge,allow_auto_merge,delete_branch_on_merge}'
```

这些参数不要求用户逐项到网页操作，也不关闭已有的其他合并方式。若当前套餐或权限不支持，报告具体未完成项，不修改质量要求。[gh repo edit](https://cli.github.com/manual/gh_repo_edit)

网页核对位置为 **Settings → General → Pull Requests**，对应字段：

- 启用 **Allow squash merging**。
- 启用 **Allow auto-merge**，供 Delivery 在验收通过后请求自动合并；必须回读 merged 状态，不能把请求接受当作已交付。条件已经满足时，也可由 Delivery 调用普通 merge API 并指定 head SHA，仍受全部质量规则约束。
- 启用 **Automatically delete head branches**。

对新建工作流而言，`aipipe-ci.yml` 是文件名，`aipipe CI` 是工作流显示名，保护规则选择的检查是 **`ci`**。不要因为文件加了前缀而额外创建一个不存在的 `aipipe-ci` required check。已有项目使用它真实产生的业务检查名。[自动合并设置](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-auto-merge-for-pull-requests-in-your-repository)、[自动删除分支](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-the-automatic-deletion-of-branches)、[检查名称规则](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/troubleshooting-rules)

需要补齐规则时优先调用 `gh api`：先 GET `repos/OWNER/REPO/rulesets` 及相关规则详情；缺少时 POST 同路径，更新时 PUT `repos/OWNER/REPO/rulesets/RULESET_ID`。请求体按下表规则生成，用 `--input` 传 JSON，并显式指定 `--method`；更新保留无关字段，写后 GET 核对。网页 **Settings → Rules → Rulesets** 作为核对或接口不可用时的回退。已有等效规则直接复用；只为缺少的职责建立以下独立规则。新建规则名称带 `aipipe-`，便于以后识别；接管项目时不重复覆盖组织级保护。

### 5.1 `aipipe-main-quality`

| 字段 | 设置 |
|---|---|
| Enforcement status | Active |
| Target branches | `main` |
| Bypass list | **空列表**，不添加任何 App 或管理员角色 |
| Require a pull request before merging | 开启，Required approvals 为 1 |
| Dismiss stale pull request approvals when new commits are pushed | 开启 |
| Require approval of the most recent reviewable push | 开启 |
| Require status checks to pass | 开启；添加实际业务检查（新项目例为 `ci`），来源选择实际产生检查的 GitHub Actions；首次业务 PR 前尚不能核验的项目单独记录 |
| Require branches to be up to date before merging | 开启 |
| Block force pushes | 开启 |
| Restrict deletions | 开启，仅保护 main |

本规则负责质量，两 App 均不能绕过。未通过 CI 或没有有效独立批准时，Delivery 也不能合并。

### 5.2 `aipipe-main-writer`

| 字段 | 设置 |
|---|---|
| Enforcement status | Active |
| Target branches | `main` |
| Restrict updates | 开启 |
| Bypass list | **仅 Delivery App** |
| Delivery 的 bypass 模式 | **For pull requests only** |
| 其他规则 | 不添加；质量由上一条规则负责 |

Delivery 只有这条“更新资格”规则的例外，仍需满足 `aipipe-main-quality`。不要把质量规则放进这条带 Delivery bypass 的规则中。

### 5.3 `aipipe-feature-writer`

| 字段 | 设置 |
|---|---|
| Enforcement status | Active |
| Target branches | `aipipe/issue-*` |
| Restrict creations | 开启 |
| Restrict updates | 开启 |
| Bypass list | **仅 Developer App** |
| Developer 的 bypass 模式 | **Always allow** |
| Restrict deletions | **关闭**，取消网页默认值 |
| 其他规则 | 不添加 |

Developer 可创建和更新 `aipipe/issue-N`；Delivery 不更新开发分支。开发分支不限制删除，使 GitHub 合并后的自动清理可以工作。检查已有组织规则和仓库规则，避免另一个规则又限制这些分支的删除。[创建规则与 bypass 模式](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)、[各规则含义](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

三条规则一起生效。Owner 仍能维护规则设置，但日常提交和合并也遵守当前规则；需要人工接管时由 Owner 明确调整写入资格，不把永久质量 bypass 当作日常入口。

若通过 API 自动创建规则，JSON 使用 `actor_type: "Integration"`，`actor_id` 为对应 **App ID**，不是 Installation ID；`bypass_mode` 分别为 `pull_request` 与 `always`。`update` 规则参数为 `{"update_allows_fetch_and_merge": false}`。不要把网页里的 App 名称直接填入数字 ID 字段。[Rulesets REST schema](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset)

## 6. 用一次小任务验证完整链路

在首次实际交付时，用当前业务 Issue 或一个有意义的小任务验证链路，例如给已有纯函数补真实边界条件测试。仅补配置时不强制另造测试任务；能从已有 PR 与工作流结果确认的项目直接复用证据。以下表格记录本次实际验证范围，未验证项保持“待验证”，不把本地文件存在当作远端已配置。

| 操作 | 身份 | 预期 | 实测记录 |
|---|---|---|---|
| 读取目标仓库、Issue、Actions 运行与 Checks | 两个 App 分别测试 | 成功 | 待验证 |
| 在 `aipipe/issue-N` 创建并推送分支、创建 PR | Developer | 成功，PR 作者为 Developer App 的 bot | 待验证 |
| Developer 提交 PR 后自动运行 `ci` | Developer 创建的 PR | 无需手工批准即可执行 | 待验证 |
| 创建 Issue、Milestone，更新任务状态 | Delivery | 成功 | 待验证 |
| 给 Developer 创建的 PR 提交 APPROVE | Delivery | 成功，并计入 required approval | 待验证 |
| 批准自己创建的 PR | Developer | 拒绝，不计为独立验收 | 待验证 |
| 有效验收后启用 auto-merge，等待 `ci` | Delivery | 未达条件时等待，条件全满足后合并 | 待验证 |
| CI 故意失败或缺少批准时请求直接合并 | Delivery | GitHub 拒绝，不加 `--admin` 重试 | 待验证 |
| 更新 main 或合并已全绿 PR | Developer | 被 main 更新资格规则拒绝 | 待验证 |
| 更新 Developer 的开发分支 | Delivery | 被开发分支更新资格规则拒绝 | 待验证 |
| 修改 `.github/workflows/` 或仓库规则 | 两个 App 分别测试 | 当前权限不足；Owner 处理 | 待验证 |
| 创建伪成功 check/status | 两个 App 分别测试 | 当前权限不足 | 待验证 |
| 合并后删除开发分支 | GitHub 自动清理 | 分支消失，Issue 关闭，PR 为 merged | 待验证 |

GitHub 不允许 PR 作者批准自己；自建 App 的 Review 是否计入当前仓库的必需批准，应以上述实测为准。[必需审批规则](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews)、[Review API](https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request)

另外分别记录 Developer 对普通 Issue、评论和 Milestone 的实际写入能力。GitHub 的部分 Issue/PR 共用端点接受 Pull requests Write；不能只凭 Issues Read 就宣称所有任务元数据修改一定返回 403。流程仍规定任务发布、状态更新由 Delivery 执行；不增加额外权限来修补一个没有用到的操作。[Issue API](https://docs.github.com/en/rest/issues/issues#update-an-issue)、[Milestone API](https://docs.github.com/en/rest/issues/milestones)

角色会话若出现与预期不符的权限，先确认 token 的 App、Installation、权限和目标仓库，并确认没有个人 token、SSH key 或凭据 helper 回退。这里的验收记录应保留具体操作、HTTP/CLI 结果和 PR 链接，不记录 token。

## 7. 更新与退出

- 私钥轮换：Owner 生成新私钥、确认签发工具可用，再删除旧私钥；不把私钥交给模型进行保管。
- 停止 aipipe：先停止宿主领取循环，收尾已有 PR，移除仅允许两个 App 的写入资格规则，再撤销专用安装授权和外部凭据。
- 业务代码、业务测试和已有 Issue/PR 记录保留。保留 CI 时可将 `aipipe-ci.yml` 改为普通工作流文件名，继续保持 check `ci`；删除工作流前，先替换或移除对应 required check，避免后续 PR 永远等待缺失的检查。
- 若未来改 check 名称，先让新检查成功运行，再切换 required checks，最后移除旧检查。[Required checks 迁移依据](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)

## 配置驱动调用

Agent 的标准调用入口是 `aipipe`，它读取 project.json、核对当前仓库、解析对应角色的 credential_ref，再调用 gh/git。外部 registry 的字段、token 文件与环境变量保存方式、轮换和例子见 [配置执行说明](configuration.md)。传统项目接入初始化负责生成这些配置；已有 aipipe 项目换机器时仅建立新的本机映射，复用既有 App。规划和发布同样可由用户选择的 AI 开发工具完成，不绑定某个模型。

既有项目先运行 `aipipe init checks --audit`，这是 Owner 只读审计，不创建规则或修改配置。核对实际生效的仓库/组织规则、传统默认分支保护、检查来源与角色写入限制；额外约束会报告，未知来源或冲突会停止。支持传统主分支保护与 feature ruleset 组合；并不自动迁移任意 legacy 通配保护。普通 App 接收端看不到 legacy 管理字段和 bypass，完整审计仍在 Owner 宿主完成。

多个必需检查使用 `ci.required_checks: [{"context":"unit","integration_id":15368},{"context":"integration","integration_id":15368}]`，通过 `config set --checks-file FILE` 登记；旧单检查配置继续支持。设置新规则时 `init checks --rules --check-sha SHA` 验证每个来源，但不会覆盖已有冲突规则。先审计，再决定本次确实缺少且授权补充的项。

共享 App：同 Owner 且权限恰好匹配角色时沿用默认接入。跨 Owner 或权限更宽的已有 App，先绑定明确的 App ID；Owner 用 `auth trust-app --role ROLE --app-owner OWNER --permissions-file FILE` 读取真实 App 并预览，再按授权加 `--apply`。FILE 是完整非秘密 App permissions 对象，必须与实际值一致并足以提供当前角色。该命令不修改 App 权限、不安装仓库、不签发 token。

信任记录保存在仓库外 `owner/trust/OWNER/REPO/ROLE.json`，绑定仓库、角色、App ID、Owner 和完整权限，0600；项目配置不能自我授权。身份/权限漂移时停止重授权。后续签发只申请当前仓库及固定角色权限，并核对返回的 token 权限后保存；共享 App 的额外权限不传给角色 token。组织安装审批/SSO 仍需账号方完成，不能把离线测试写成真实组织已验证。
