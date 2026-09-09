# 原生测试与大型项目接入

aipipe 不提供语言运行时或测试适配引擎。先读取项目已有配置与检查，沿用可用入口；用户只要求局部工作时不强制迁移框架。下表为新建入口时的参考，脚本名和版本按业务项目实际确定。

| 项目 | 常用入口 | 必须明确的前提 |
|---|---|---|
| Vue / Vite | `npm ci`、`npm run test:unit`、`npm run build` | 使用项目实际包管理器和锁文件；`test:unit` 调用非 watch 的 `vitest run` |
| Vue + TypeScript | 增加 `npm run typecheck`，如 `vue-tsc --noEmit` | Vite 构建不做类型检查；已有等价脚本直接复用 |
| Vue 组件与 E2E | Vue Test Utils；必要路径用 Playwright | 组件测试断言用户行为；完整 E2E 启动实际后端及隔离数据，不能将全部 API mock 后声称完整链路通过 |
| Java / Maven | 仓库已有 `./mvnw -B verify`，没有 Wrapper 时沿用已固定的 Maven | JUnit / Surefire 单元测试；需要的 Failsafe 必须绑定 integration-test 和 verify |
| Java / Gradle | `./gradlew build`，仅验证可用 `./gradlew check` | 额外 integrationTest suite 必须显式接入 check，不能假定默认执行 |

官方依据：[Vue 测试](https://vuejs.org/guide/scaling-up/testing.html)、[Vue 类型检查](https://vuejs.org/guide/typescript/overview.html)、[Vitest run](https://vitest.dev/guide/cli)、[Playwright CI](https://playwright.dev/docs/ci)、[Maven Failsafe](https://maven.apache.org/surefire/maven-failsafe-plugin/usage.html)、[Gradle 测试套件](https://docs.gradle.org/current/userguide/jvm_test_suite_plugin.html)。

Vue 测试保留在项目组件测试目录和 `e2e/`，Java 保留各模块 `src/test/java/` 与 `src/test/resources/`。产品脚本、测试配置和依赖不导入 `.aipipe/`。

## 每个 Issue 同时交付代码和测试

- 新功能：正常路径、关键边界、错误行为。
- 缺陷修复：能复现缺陷并证明修复的回归用例。
- 接口：请求、响应、状态码、权限与兼容约定。
- 跨模块：调用方和被调用方的契约，必要集成回归。

测试断言可观察行为，不只检查函数调用次数或代码文本。验收者独立检查测试有效性，CI 在干净环境执行相同的产品命令。CI 不能仅运行 `.aipipe/tests/` 就声称业务通过；需要业务测试的套件没有发现测试时应失败。聚合 POM、BOM、纯配置模块不必制造无意义用例。

## 确認原生检查实际覆盖源码

首片建立检查脚本时核对被检查文件与实际运行入口，不能只看退出码。TypeScript 的根 tsconfig 若是 `files: []` 加 references，普通 `tsc --noEmit` 不会遍历引用项目；可按项目结构使用 build 模式或逐个 `tsc -p ... --noEmit`，并核对应用、工具配置和测试文件的覆盖范围。[TypeScript project references](https://www.typescriptlang.org/docs/handbook/project-references)

React 的组件测试应覆盖实际应用入口使用的 StrictMode。读取持久化数据和初始化写入要避免用初始空状态覆盖已有数据；异常存储按项目契约保留原始值并展示警告。不要通过移除 StrictMode 或弱化刷新断言消除失败。[React StrictMode](https://react.dev/reference/react/StrictMode)

## 配置业务 CI

由 Owner 或具备对应授权的配置身份修改工作流；Developer / Delivery 默认不授予 Workflows Write。复用已有业务 CI 时保留名称；新增 aipipe 工作流放在 `.github/workflows/aipipe-ci.yml`，显示名可为 `aipipe CI`。

根据实际项目生成完整工作流，包含：触发目标分支 PR 和目标分支 push、只读权限、干净 checkout、项目固定版本、安装声明依赖、测试与构建、必要隔离服务和明确超时。先验真实输出，再将实际 job/check 加到保护规则。Action 版本按项目依赖政策选择和固定，不凭模板中的工具测试结果宣告业务已验收。

空项目的首业务 PR 同时建立实际实现、有效用例和原生测试入口。CI 尚未产生时可以做规划和开发；合并前必须确认真实必需检查和独立审批规则有效。不能用必过示例绕开空测试门禁。

## 大型项目

同仓库 Vue + Java 可以使用一个 workflow，前端、后端及必要集成测试 job 并行，稳定的汇总 job 作为必需检查。汇总在依赖完成后始终执行，只有本次必需 job 全部成功才通过；失败、取消或意外跳过不能变成通过。不要在工作流层过滤路径，造成必需检查不产生。[GitHub 必需检查故障说明](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)

起步跑完整的必要检查，实际耗时成为问题后再按已有构建依赖图选模块、缓存或分片。公共库、契约、数据库迁移和根构建配置变更覆盖相关消费者；无法确定影响时回退完整回归。Maven 的 `-am` 只增加上游依赖，不能代替下游消费者回归。[Maven 多模块](https://maven.apache.org/guides/mini/guide-multiple-modules.html)

按业务模块和近期里程碑规划，按独立可验收行为拆 Issue，控制每次 Agent 需要读取的设计范围；跨模块接口先给版本和兼容策略。大型项目仍可串行交付切片，测试 job 并行不需要并行领取 Issue。多仓库项目各自一 Issue、一分支、一 PR，以带仓库名的依赖链接协调，不承诺跨仓库原子合并。

本模板给出接入约定，没有内置一个已验收的 Vue 或 Java 业务系统。技术栈的端到端支持须用真实业务切片验收。
