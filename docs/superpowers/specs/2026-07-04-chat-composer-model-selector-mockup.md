# Chat Composer 2.0 — ModelSelector 视觉模版 (Task 3 实现依据)

> Status: 方向 B(芯片图标 + Auto 显全局名)· Date: 2026-07-04 · 配套 spec: `2026-07-03-chat-composer-model-switch-design.md`
> 本文档是 Task 3 前端实现的像素级依据。所有类名取自现有设计系统(tailwind.config.ts HSL tokens + Outfit/JetBrains Mono),不引入任何新依赖(`@radix-ui/react-popover@^1.1.15` 已安装,本组件是其首个使用点)。

## 0. 设计原则

**融入,不打断。** Composer 是用户每次打字都盯着的地方——选择器必须和右侧的回形针/发送按钮同属一个"安静工具行",默认态几乎隐形(muted),交互态才亮起(primary)。参照系:现有 detail `<select>` 的视觉重量(text-[11px] muted 无边框)是上限,不能更重。

## 1. Pill(触发器)— 三种状态

替换 `ChatInput.tsx:176-189` 的 detail `<select>`,位置不变(composer 圆角容器内最左)。

### 1.1 Auto 态(默认,新会话)

```
┌─ composer rounded-3xl ────────────────────────────────────────────┐
│  ⬡ Auto · Opus 4.8 ⌄   📎  │ Ask about AWS resources…        ↑  │
└───────────────────────────────────────────────────────────────────┘
     └── pill:芯片icon + "Auto"(foreground) + "· Opus 4.8"(muted) + chevron
```

- "Auto" 用 `text-muted-foreground`;解析出的全局模型名 `· Opus 4.8` 用 `text-muted-foreground/60`(更淡一档,表明"这是跟随,不是选择")
- 全局名来源:presets 中匹配 `GET /api/settings`.`agent_models.main` 的 label;匹配不到则 `shortName(model_id)`

### 1.2 已选态(session 有 model_id)

```
│  ⬡ Opus 4.8 ⌄   📎  │ Ask about AWS…                          ↑  │
     └── 模型名用 text-primary-600 dark:text-primary-400(轻微上色,可感知"我改过")
```

### 1.3 Streaming 禁用态

```
│  ⬡ Opus 4.8 ⌄   📎  │ (streaming…)                            ■  │
     └── opacity-50 cursor-not-allowed;hover 出 Tooltip:"回复生成中,停止后可切换"
```

### Pill 精确类名

```tsx
// 容器(button,Popover.Trigger asChild)
className="self-center flex items-center gap-1 max-w-[180px] px-2 py-1 rounded-lg
           text-[11px] text-muted-foreground
           hover:bg-muted hover:text-foreground
           disabled:opacity-50 disabled:cursor-not-allowed
           focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/30
           transition-colors cursor-pointer"
// 芯片 icon:w-3.5 h-3.5,stroke=currentColor,strokeWidth 1.5(和 IconSidebar 一致)
// 模型名 span:truncate;已选态加 text-primary-600 dark:text-primary-400 font-medium
// Auto 后缀 span:text-muted-foreground/60 truncate
// chevron:w-3 h-3,open 态 rotate-180 transition-transform
```

芯片 SVG path(cpu/chip,24×24 viewBox,和现有线性图标同族):
```
M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2
M7 5h10a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V7a2 2 0 012-2z
M10 10h4v4h-4z
```

## 2. Popover(向上弹出)

```
        ┌──────────────────────────────────┐
        │  ✓  Auto                         │ ← 选中行:check primary-600
        │     跟随全局 · Opus 4.8            │ ← 副行 text-[10px] muted/60
        │ ──────────────────────────────── │ ← Separator: h-px bg-border my-1
        │     Opus 4.8                     │
        │     claude-opus-4-8              │ ← id 副行:font-mono text-[10px] muted/50
        │     Opus 4.7                     │
        │     claude-opus-4-7              │
        │     Sonnet 4.6                   │
        │     claude-sonnet-4-6            │
        │     Haiku 4.5                    │
        │     claude-haiku-4-5-20251001…   │
        │     Claude                       │
        │     claude-fable-5               │ ← 两个 label 同为 "Claude":id 副行是唯一消歧
        │     Claude                       │
        │     claude-sonnet-5              │
        └──────────────────────────────────┘
          ▲ 从 pill 向上弹(side="top" align="start" sideOffset=8)
```

### Popover 精确规格

```tsx
<Popover.Portal>
  <Popover.Content side="top" align="start" sideOffset={8}
    className="w-64 max-h-80 overflow-y-auto p-1 rounded-xl
               bg-card border border-border shadow-lg z-50
               data-[state=open]:animate-in data-[state=open]:fade-in-0
               data-[state=open]:slide-in-from-bottom-2">
```

- 房子风格对齐:`bg-card border border-border shadow-lg z-50` 与 IconSidebar Tooltip.Content 完全一致;圆角升到 `rounded-xl`(内容型浮层比 tooltip 大一档)
- 动画:tailwindcss-animate 已装,用 `fade-in-0 slide-in-from-bottom-2`(150ms 默认),不加自定义 keyframe

### 列表项(button,每项两行)

```tsx
className="w-full flex items-start gap-2 px-2.5 py-1.5 rounded-lg text-left
           hover:bg-muted focus:bg-muted focus:outline-none transition-colors"
// 第1行 label:text-xs text-foreground;选中项 font-medium
// 第2行 id:  font-mono text-[10px] text-muted-foreground/50 truncate
// check 图标:w-3.5 h-3.5 text-primary-600 dark:text-primary-400;未选中项占位 w-3.5(对齐)
// Auto 项副行:`跟随全局 · ${globalLabel}`(非 mono,text-muted-foreground/60)
```

- 项间无分隔线,只有 Auto 与 presets 之间一条 `<div className="h-px bg-border my-1 mx-2" />`
- 选择即关(onSelect → PATCH → close);PATCH 失败(400/409)→ 保持原选中,在 pill 下方不弹全局 toast,复用 composer 现有 attachError 行样式显示一行 `text-xs text-red-500` 错误(3s 自动消失)

## 3. 状态机与数据流

```
pill 显示 = session.model_id
  ? presetLabel(model_id) ?? shortName(model_id)     // 已选态
  : `Auto · ${presetLabel(globalMainModel) ?? shortName(globalMainModel)}`

onSelect(value):
  value === current → 仅关闭
  PATCH /api/chat/sessions/{id} {model_id: value}    // "" = Auto
    200 → useQueryClient().setQueryData 更新 session 缓存 → pill 立即变
    409 → 错误行:"回复生成中,停止后可切换"
    400 → 错误行:"该模型不可用"
```

- `shortName(id)`:复用 AgentMetrics.tsx:151 的 `id.split(".").slice(2).join(".")` 约定(去 `global.anthropic.` 前缀)——抽到 `lib/modelName.ts` 供两处共用
- presets 来源:现有 `useSettings()`(`model_presets` 字段),无新请求
- 全局 main 模型:`useSettings()`.`agent_models.main`(GET /api/settings 已返回;若字段名不同以实际为准)

## 4. 边界情况

| 场景 | 行为 |
|---|---|
| **Welcome 模式**(session 未创建) | pill 照常显示、可打开可选择;选择结果存组件 state,`useLazySessionCreate` 创建 session 后立刻补一个 PATCH 带上 model_id。不新增后端参数(POST /sessions 不加字段,保持 API 面最小) |
| **Streaming 中** | pill `disabled` + Tooltip(§1.3);后端 409 是兜底,前端禁用是第一道 |
| **presets 为空**(Bedrock 拉取失败且无 alias) | pill 只显示 "Auto",点击弹出仅含 Auto 一项 + muted 提示行 "模型列表不可用" |
| **session.model_id 不在 presets 里**(如全局配置后来删了该模型) | pill 显示 `shortName(model_id)` 照常;popover 里该值不在列表 → 顶部额外显示当前值一行(选中态,muted 注 "不在当前列表") |
| **两个 label 均为 "Claude"** | id 副行天然消歧,不做特殊处理 |
| **键盘** | Radix Popover 原生:Esc 关、Tab 循环;列表项是 button 可 Enter 选 |

## 5. i18n 键(en.json / zh.json 各 4 个,flat)

```json
"chat.model.auto": "Auto" / "自动",
"chat.model.followGlobal": "Follows global · {model}" / "跟随全局 · {model}",
"chat.model.streamingLocked": "Streaming — stop the response to switch models" / "回复生成中,停止后可切换模型",
"chat.model.unavailable": "Model list unavailable" / "模型列表不可用"
```

## 6. 组件与文件

```
新增: src/agenticops/web/frontend/src/components/chat/ModelSelector.tsx   (~120 行)
新增: src/agenticops/web/frontend/src/lib/modelName.ts                    (shortName + presetLabel)
修改: ChatInput.tsx  — detail <select> → <ModelSelector sessionId={} disabled={} />
修改: Chat.tsx       — 传 sessionId;welcome 模式传 onModelPreselect
```

Props:
```tsx
interface ModelSelectorProps {
  sessionId: string | null;          // null = welcome 模式(本地暂存)
  streaming?: boolean;               // 禁用 + tooltip
  preselected?: string;              // welcome 模式的本地暂存值(受控)
  onPreselect?: (modelId: string) => void;  // welcome 模式回调
}
```

## 7. 暗色模式核对清单

全部走 token,无硬编码色:`bg-card/bg-muted/border-border/text-foreground/text-muted-foreground` 自动翻转;仅两处显式 dark 变体:选中色 `text-primary-600 dark:text-primary-400`(与 colors.ts severity 模式一致)、错误行沿用现有 `text-red-500`。
