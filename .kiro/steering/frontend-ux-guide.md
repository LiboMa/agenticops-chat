---
inclusion: auto
---

# 前端 UX 开发规范

## 设计系统

### 主题
- 使用 CSS Variables（shadcn 风格），定义在 `src/index.css`
- Light 模式：蓝色主色调（`--primary: 221 83% 53%`）
- Dark 模式：绿色主色调（`--primary: 142 71% 45%`），纯黑背景（`--background: 0 0% 4%`）
- 所有颜色通过 `hsl(var(--xxx))` 引用，不要硬编码颜色值

### 字体
- 主字体：Outfit（Google Fonts），`font-family: "Outfit", ui-sans-serif, system-ui`
- 数据/代码：`font-mono`（系统等宽字体）

### 间距与排版
- 标签文字：`text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground`
- 数值展示：`text-3xl font-light tracking-tight font-mono`
- 正文：`text-sm`，行高 `leading-relaxed`
- 页面内边距：`p-6`（由 AppShell 提供）
- 卡片间距：`gap-4` 或 `gap-6`

### 动画
- 入场动画：`duo-fade`（translateY 6px → 0，0.35s ease-out）
- 脉冲指示：`duo-pulse`（opacity 闪烁，2s）
- 交错动画：通过 `style={{ animationDelay: '${i * 70}ms' }}` 实现

## 组件规范

### 通用组件（`components/ui/`）
| 组件 | 用途 |
|------|------|
| `Card` / `CardHeader` / `CardBody` | 内容容器 |
| `Badge` | 标签/状态标记 |
| `DataTable` | 可排序数据表格 |
| `Spinner` | 加载指示器 |
| `ErrorBanner` | 错误提示（带重试按钮） |
| `EmptyState` | 空状态占位 |
| `ConfirmDialog` | 确认对话框（`useConfirm` hook） |
| `SeverityBadge` | 严重程度标记（critical/high/medium/low） |
| `IssueStatusBadge` | Issue 状态标记 |
| `FixPlanStatusBadge` | Fix Plan 状态标记 |
| `RiskLevelBadge` | 风险等级标记（L0-L3） |
| `PipelineStepper` | Pipeline 进度条 |
| `IssueStatusStepper` | Issue 生命周期步骤条 |
| `IssueActionBar` | Issue 智能操作栏 |
| `IssueRow` | Issue 列表行 |
| `StatCard` | 统计卡片 |
| `StatusIndicator` | 状态指示器 |

### 布局组件（`components/layout/`）
- `AppShell`：主布局壳（侧边栏 + 顶栏 + 内容区）
- `IconSidebar`：52px 图标导航栏，Radix Tooltip
- `MinimalTopBar`：顶部工具栏

### Chat 组件（`components/chat/`）
- `ChatInput`：输入框（支持文件上传、详细度选择）
- `MessageList`：消息列表（支持流式内容）
- `SessionFlyout`：会话侧边栏
- `ContextPanel`：右侧上下文面板
- `DragHandle`：可拖拽分割线
- `ToolCallChip`：工具调用标记
- `TokenMetrics`：Token 使用量展示
- `SaveReportDialog`：保存为报告对话框

## 数据获取模式

### React Query Hooks（`hooks/`）
- 所有 API 调用通过 TanStack Query hooks 封装
- 命名规范：`use{Entity}` 查询，`use{Action}{Entity}` 变更
- 查询配置：`retry: 1`，`refetchOnWindowFocus: false`
- 示例：`useStats()`、`useAnomalies()`、`useFixPlans()`、`useCreateChatSession()`

### API 客户端（`api/client.ts`）
- 基础 URL：`/api`
- 统一错误处理：`ApiError` 类（status + message）
- 所有请求默认 `Content-Type: application/json`

### 类型定义（`api/types.ts`）
- 所有 API 响应类型集中定义
- 与后端 Pydantic 模型对应

## 国际化（i18n）
- 使用自定义 `LocaleContext`（非第三方库）
- 支持 `en` / `zh` 双语
- 翻译文件：`locales/en.json`、`locales/zh.json`
- 使用方式：`const { t } = useLocale(); t("key.path")`
- 新增文案时必须同时更新两个语言文件

## 路由结构
```
/app                    → Dashboard
/app/chat               → Chat（自动创建新 Session）
/app/chat/:sessionId    → Chat（指定 Session）
/app/issues             → Issues & Plans
/app/issues/:id         → Issue Detail
/app/resources/:id      → Resource Detail
/app/reports            → Reports
/app/reports/:id        → Report Detail
/app/schedules          → Schedules
/app/schedules/:id      → Schedule Detail
/app/settings           → Settings
```

## UX 交互模式

### 状态展示
- 使用颜色编码的 Badge 表示状态（severity、issue status、fix plan status、risk level）
- 空状态使用虚线边框 + 居中文案 + 图标
- 加载状态使用 `<Spinner />` 组件

### 表格交互
- `DataTable` 支持列排序（点击表头）
- 行可点击（hover 高亮 `bg-accent`）
- 分页控件在表格底部

### 过滤与搜索
- 阶段过滤使用 chip 按钮组（带计数 badge）
- 搜索框带搜索图标前缀
- 下拉筛选使用原生 `<select>` 样式化

### 操作反馈
- 操作消息使用 `actionMsg` 状态 + 彩色 banner
- 确认操作使用 `useConfirm` hook + `ConfirmDialog`
- 异步操作按钮显示 loading 文案（如 "Analyzing..."、"Executing..."）

## 开发注意事项

### 新增页面
1. 在 `pages/` 创建页面组件
2. 在 `App.tsx` 添加 lazy import + Route
3. 在 `IconSidebar.tsx` 的 `NAV_ITEMS` 添加导航项（如需要）
4. 更新 `locales/en.json` 和 `locales/zh.json`

### 新增 API 调用
1. 在 `api/types.ts` 定义类型
2. 在 `hooks/` 创建 React Query hook
3. 使用 `apiFetch<T>()` 调用 API

### 样式规范
- 优先使用 Tailwind 工具类
- 颜色使用 CSS Variable：`text-foreground`、`bg-card`、`border-border` 等
- 不要使用硬编码的颜色值（如 `text-gray-500`），使用语义化变量
- 交互状态：`hover:bg-accent`、`hover:text-foreground`、`transition-colors`
- 圆角：`rounded-lg`（默认）、`rounded-md`（小元素）、`rounded-full`（圆形）
