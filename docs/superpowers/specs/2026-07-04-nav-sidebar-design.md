# Nav Sidebar 2.0 — 拖拽排序 + 展开/收起 + hover 预览 — Design Spec

> Status: **draft — 三项交互决策取推荐项(用户暂离),待用户审阅确认** · Date: 2026-07-04 · Branch: `MVP-2.0.1`
> Sub-project C(导航栏优化)。原始需求:drag-to-reorder、thumbnails、text+icon 共存。

## 1. 决策(推荐项,待确认)

| 决策 | 取值 | 理由 |
|---|---|---|
| 文字+图标形态 | **可切换展开/收起**:收起 52px 纯图标(现状),展开 200px 图标+文字;底部折叠按钮;默认收起 | 熟手省空间、新手要文字;永久展开挤压 chat 三栏;hover 自动展开易误触 |
| "缩略图"语义 | **hover 预览卡片**:tooltip 升级为小卡片 = 页面名 + 一行实时摘要(Issues → "53 open · 14 critical";Chat → "N sessions";Schedules → 下次执行时间) | 数据全部来自已有 `useStats`/`useChatSessions` 缓存,零新后端;真截图方案重且易过期 |
| 排序持久化 | **localStorage**(`aiops-nav-order`,usePersistedState 现成,跨标签页同步) | 个人偏好级别;服务端用户偏好表 YAGNI |
| 拖拽实现 | **原生 HTML5 DnD**(draggable + dragover/drop),不引入 dnd-kit | 7 个条目的垂直列表,原生足够;不加依赖(项目铁律);ChatInput 已有同款原生 DnD 先例 |

## 2. 现状(侦察结论)

- `IconSidebar.tsx`(117 行):`NAV_ITEMS` 常量数组(7 项 `{to, icon, labelKey, end, badge?}`)+ Radix Tooltip;固定 `w-[52px]`,`aside fixed` + zIndex 30。
- `AppShell.tsx`:内容区 `pl-[52px]` **硬编码**——展开态需要联动(52↔200px,transition)。
- Settings 入口固定底部,不参与排序。
- 无任何拖拽依赖;`usePersistedState` 已有跨 tab 同步。

## 3. 设计

### 3.1 组件结构(重构 IconSidebar → 3 个文件,职责单一)

```
components/layout/
  IconSidebar.tsx     → 保留壳:渲染态(collapsed/expanded)+ 底部折叠按钮 + Settings
  NavItems.tsx        (新) 可排序导航列表:排序 state、HTML5 DnD、渲染 NavLink
  NavPreviewCard.tsx  (新) hover 预览卡片(Radix Tooltip.Content 的内容升级)
```

### 3.2 数据流

- **排序**:`NAV_ITEMS` 增加稳定 `id`;`usePersistedState<string[]>("aiops-nav-order", 默认序)` 存 id 数组。渲染序 = 存储序 ∩ 现存项(新增页面自动 append,已删页面自动忽略——版本升级安全)。
- **展开态**:`usePersistedState<boolean>("aiops-nav-expanded", false)`。`AppShell` 从同一 key 读取(或 IconSidebar 通过 CSS 变量 `--sidebar-w` 输出),内容区 `pl` 跟随 52↔200px,`transition-[padding]`。
- **拖拽**:条目 `draggable`;`dragstart` 记 sourceId;`dragover`(preventDefault)算落点显示 2px primary 指示线;`drop` 重排数组写回。仅展开态启用拖拽(收起态 40px 高图标拖拽误触率高;简化)。
- **预览卡片**:Tooltip.Content 内容从纯文本升级为卡片(`w-48`):页面名(text-xs font-medium)+ 摘要行(text-[11px] muted)。摘要数据源:
  - Dashboard/Issues → `useStats()`(已有,60s refetch)
  - Chat → `useChatSessions()` 长度
  - Schedules/Reports/Skills/Metrics → 各自已有 list hook 的 `data?.length`(**只读缓存,`enabled:false` 不主动发请求**——缓存为空则只显示页面名,绝不因 hover 触发 N 个请求)

### 3.3 错误处理

| 场景 | 行为 |
|---|---|
| localStorage 里的 order 含未知 id / 缺新 id | 交集+append 算法自愈,无需迁移 |
| 拖拽中 Esc / 拖出边界 | dragend 清指示线,不改序 |
| stats 缓存为空 | 卡片只显示页面名(与现 tooltip 等价降级) |

### 3.4 测试

- vitest:排序算法纯函数(`reorderNavIds(stored, current)` 交集+append;drop 重排);展开态 class 断言。
- `npx tsc --noEmit` + `npm run build`。
- Playwright E2E:展开 → 文字出现、内容区 padding 联动;拖 Issues 到顶部 → 刷新后顺序保持;hover Issues → 卡片显示 open/critical 数;收起 → 恢复 52px 纯图标。

## 4. 明确不做(YAGNI)

- dnd-kit / 任何新依赖
- 服务端用户偏好存储
- 页面真实截图缩略图
- 收起态拖拽、嵌套分组、隐藏导航项
- MinimalTopBar / CommandPalette 改动

## 5. Brainstorm 过程留档

侦察:IconSidebar 117 行 NAV_ITEMS 常量、AppShell `pl-[52px]` 硬编码、usePersistedState 已带跨 tab 同步、无拖拽依赖。方案对比:展开形态(切换/永久/hover 自动)取切换;缩略图(预览卡/真截图/砍掉)取预览卡;持久化(localStorage/服务端)取 localStorage;拖拽(原生/dnd-kit)取原生——dnd-kit 违反"不加没用依赖"铁律且 7 项垂直列表用不上其能力。三项交互决策在用户暂离时按推荐项采纳,spec 状态标 draft 待确认。
