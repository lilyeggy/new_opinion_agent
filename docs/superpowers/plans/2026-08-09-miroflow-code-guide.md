# MiroFlow Code Guide Implementation Plan

> **For agentic workers:** Execute this plan inline and verify each checkpoint before continuing.

**Goal:** 构建一个可交互、可按阅读路线逐层学习的 MiroFlow 中文源码讲解网页。

**Architecture:** 页面作为独立静态站点，不修改 MiroFlow 参考仓库；内容以本地浅克隆 commit `fca7b4a7fda30e5a17b5c7b73d780738a925869f` 为准。HTML 负责语义内容，CSS 负责响应式视觉系统，JavaScript 负责架构导航、运行循环步进、源码模块筛选、故障场景和阅读进度。

**Tech Stack:** Semantic HTML、CSS、Vanilla JavaScript，无构建依赖、无网络运行依赖。

---

## 文件结构

- `miroflow_code_guide/index.html`：学习站结构、核心讲解、源码片段和无脚本可读内容。
- `miroflow_code_guide/styles.css`：响应式布局、架构图、代码阅读和交互状态。
- `miroflow_code_guide/app.js`：架构节点选择、Agent Loop 步进、文件筛选、故障场景和阅读进度。

## 实施任务

### 任务 1：固定源码事实

- 核对入口、pipeline、orchestrator、ToolManager、LLM adapter、TaskTracer、prompt、search/read 工具和 benchmark runner。
- 每个讲解结论都标注本地文件路径与关键符号；区分本地代码事实、在线新版文档和对 OpinionSearch 的设计建议。

### 任务 2：建立学习信息架构

- 提供项目定位与版本提示。
- 提供可点击架构地图和一次完整运行的步进视图。
- 提供按重要性分级的源码地图和四阶段阅读路线。
- 提供核心文件深度讲解、真实代码片段、失败恢复实验和 OpinionSearch 对照。

### 任务 3：实现交互

- 架构节点选择后同步更新职责、输入输出和关键源码。
- Agent Loop 支持前后步进与直接选择。
- 源码地图支持按层次筛选和文本搜索。
- 故障实验支持切换错误类型并显示真实恢复路径与局限。
- 阅读清单保存到浏览器本地存储并显示进度。

### 任务 4：验证

- 检查所有脚本引用、DOM 选择器和交互状态。
- 在桌面和移动宽度检查布局、导航、代码块和按钮可用性。
- 核对本地源码路径、符号名、commit 和版本差异说明。
- 页面不依赖 API key、外部服务或 MiroFlow 运行环境即可阅读和交互。
