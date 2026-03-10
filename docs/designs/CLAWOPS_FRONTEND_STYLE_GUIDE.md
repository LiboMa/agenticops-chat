# ClawOps Frontend Style Guide v1.0

> Ma Ronnie 指令：模仿 ChatGPT 风格，极简克制，实用

## 设计原则

1. **极简** — 去掉一切不必要的装饰
2. **克制** — 不加任何"看起来很酷但没用"的东西
3. **实用** — 每个元素都有明确用途
4. **前后端一致** — API 返回什么，前端展示什么，不多不少

## ChatGPT 设计语言提炼

### 色彩
```
背景:       #212121 (深灰，不是纯黑)
卡片/面板:   #2f2f2f (稍亮的灰)
边框:       #424242 (微弱分隔)
主文字:     #ececec (近白)
次要文字:   #9b9b9b (灰色)
强调色:     #10a37f (ChatGPT 绿，ClawOps 可用 #3b82f6 蓝)
Hover:      #383838
```

### 字体
```
正文: system-ui, -apple-system, sans-serif  (16px)
代码: 'Söhne Mono', 'JetBrains Mono', monospace (14px)
行高: 1.5
字重: 400 (正文), 600 (标题)
```

### 布局
```
Sidebar:    260px 宽, 固定左侧, #171717 背景
内容区:     居中, max-width 768px (单栏), 或 full-width (表格/列表)
间距:       16px 基础单元, 卡片间 12px
圆角:       12px (卡片), 8px (按钮), 20px (输入框)
```

### Sidebar 风格 (ChatGPT 式)
- 纯文字导航，无图标（或极简图标）
- 选中项: 浅灰背景 `#2f2f2f` + 圆角
- Hover: `#383838`
- 分组用细线或微小标题（不用大标题）
- 底部: Settings + 用户信息

### 卡片
- 无阴影，用 1px border `#424242`
- 圆角 12px
- 内边距 16px
- 标题 16px 600 weight，正文 14px 400 weight

### 按钮
- Primary: 白色文字 + 强调色背景
- Secondary: 灰色边框 + 透明背景
- 不要渐变、不要阴影、不要动画
- Hover: 微调明度即可

### 表格/列表
- 无边框表格，行间用 1px border-bottom
- Hover 整行 `#383838`
- 表头 12px uppercase 灰色

### 数据展示
- 数字大而醒目（32px bold）
- 标签小而灰（12px #9b9b9b）
- 状态用小圆点 + 文字（不用 badge）
- 空状态: 居中灰色文字，不要插图

## 不要做的事

- ❌ 渐变色
- ❌ 阴影 (box-shadow)
- ❌ 动画/过渡效果（除了基础 hover 0.15s）
- ❌ 大图标/emoji 导航
- ❌ 卡片内嵌卡片
- ❌ 彩色 badge（用灰度 + 小圆点色标）
- ❌ 空白页放大 SVG 插图
- ❌ 任何"花里胡哨"的东西

## Tailwind CSS 映射

```css
/* 背景 */
.bg-main    { @apply bg-[#212121]; }
.bg-card    { @apply bg-[#2f2f2f]; }
.bg-sidebar { @apply bg-[#171717]; }
.bg-hover   { @apply bg-[#383838]; }

/* 文字 */
.text-primary   { @apply text-[#ececec]; }
.text-secondary { @apply text-[#9b9b9b]; }

/* 边框 */
.border-subtle { @apply border-[#424242]; }

/* 圆角 */
.rounded-card { @apply rounded-xl; }  /* 12px */
.rounded-btn  { @apply rounded-lg; }  /* 8px */
.rounded-input { @apply rounded-[20px]; }
```

## 实施优先级

1. **Sidebar** — 去掉 emoji，纯文字，ChatGPT 风格
2. **全局色彩** — 统一为上述色板
3. **Dashboard** — 简化卡片，大数字 + 灰标签
4. **Issues 列表** — 无边框表格 + hover 行
5. **Issue Detail** — 单栏布局，Timeline 简洁展示
6. **其他页面** — 逐步统一

## 第二轮优化 — 设计质量（不是换色）

> Ma Ronnie: "太烂了" — 第一轮只做了颜色替换，没做设计打磨

### 布局
- **单栏居中**: `max-w-4xl mx-auto` 用于详情页（AnomalyDetail, FixPlanDetail）
- **内边距统一**: 页面 `p-6`，卡片 `p-4`
- **卡片间距**: `gap-4`（16px）
- **呼吸感**: 区块间用 `mt-8` 或 `mb-8` 分隔

### AnomalyDetail（核心页面）
- 顶部: 标题 + severity dot + 状态，一行搞定
- RCA 结论: 单独大卡片，根因加粗，confidence 小字灰色
- Timeline: 垂直线 + 小圆点，每个事件一行，不要卡片
- Recommendations: 简单编号列表
- 去掉所有信息密度过高的区域

### FixPlanDetail（核心页面）
- 步骤: 编号 + 描述，不要嵌套卡片
- 执行状态: 顶部 banner（绿/红/灰）
- 审批按钮: 底部固定，Primary + Secondary 样式

### 表格/列表
- 行高: `py-3`（不要太紧凑）
- 列宽: 第一列（标题）占 60%，其余均分
- 空表格: 居中 "No data" 灰色文字

### 表单/输入
- 输入框: `rounded-[20px]` pill 形，`bg-[#383838]` 背景
- 按钮间距: `gap-3`
- Label: 12px uppercase 灰色，`mb-1`

### 动画/过渡
- 只保留: `transition-colors duration-150`（hover 背景色）
- 去掉: `hover:-translate-y-0.5`、`hover:shadow-lg`、所有 scale/transform

### 拓扑图（Network）
- 节点 shadow 保留（功能性，区分层级）
- 但 `from-purple-50` 等 light 渐变 → 改成 dark 渐变（`from-purple-900/20`）
- highlighted ring 可以保留

## 参考

- ChatGPT (chatgpt.com) — 主要参考
- Linear (linear.app) — 表格/列表参考
- Vercel Dashboard — 极简数据面板参考
