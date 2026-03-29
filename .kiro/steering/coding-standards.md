---
inclusion: auto
---

# 编码规范

## 前端（React + TypeScript）

### 文件组织
- 页面组件：`src/pages/{PageName}.tsx`（default export，lazy loaded）
- UI 组件：`src/components/ui/{ComponentName}.tsx`（named export）
- 布局组件：`src/components/layout/{ComponentName}.tsx`
- 业务组件：`src/components/{domain}/{ComponentName}.tsx`
- Hooks：`src/hooks/use{Name}.ts`
- API 类型：`src/api/types.ts`（集中定义）
- 工具函数：`src/lib/{name}.ts`

### 组件规范
- 页面组件使用 `export default function PageName()`
- UI 组件使用 `export function ComponentName()`
- Props 使用内联类型或独立 interface
- 使用 `useLocale()` 的 `t()` 函数处理所有用户可见文案
- 加载状态使用 `<Spinner />`，错误状态使用 `<ErrorBanner />`

### 样式规范
- 使用 Tailwind CSS 工具类
- 颜色使用语义化 CSS Variable：`text-foreground`、`bg-card`、`border-border`
- 不使用硬编码颜色（如 `text-gray-500`），除非是特定状态色（如 `text-red-500` 用于错误）
- 交互状态：`hover:bg-accent`、`transition-colors duration-150`
- 间距：使用 Tailwind 的 spacing scale（`gap-4`、`p-6`、`mb-3` 等）

### 数据获取
- 所有 API 调用通过 `hooks/use*.ts` 中的 React Query hook
- 查询 hook：`useQuery` + `queryKey` + `queryFn`
- 变更 hook：`useMutation` + `onSuccess` 中 `invalidateQueries`
- API 调用使用 `apiFetch<T>(path, options)`

## 后端（Python / FastAPI）

### 文件组织
- API 端点：`web/app.py`
- 数据模型：`models.py`
- 配置：`config.py`
- 服务层：`services/{service_name}.py`
- Agent：`agents/{agent_name}.py`
- 工具：`tools/{tool_category}_tools.py`

### 代码规范
- 类型注解：所有函数参数和返回值
- 文档字符串：模块级和公共函数
- 日志：使用 `logging.getLogger(__name__)`
- 数据库操作：使用 `get_db_session()` 上下文管理器
- 配置访问：通过 `settings` 单例

### API 规范
- 请求/响应使用 Pydantic BaseModel
- 路径参数用于资源标识（如 `/issues/{id}`）
- 查询参数用于过滤和分页
- POST 用于创建和触发操作
- PUT/PATCH 用于更新
- DELETE 用于删除
- 错误使用 HTTPException

## 通用规范

### Git 提交
- 提交信息格式：`type(scope): description`
- type：feat / fix / refactor / style / docs / test / chore

### 国际化
- 新增用户可见文案必须同时更新 `locales/en.json` 和 `locales/zh.json`
- key 使用点分路径：`section.subsection.key`

### 构建与测试
- 前端构建：`cd src/agenticops/web/frontend && npm run build`
- 前端开发：`cd src/agenticops/web/frontend && npm run dev`
- 后端启动：`aiops service start` 或 `aiops web`
- 后端测试：`pytest`
