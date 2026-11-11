# 开发进度 Dashboard

打开 `docs/progress/dashboard.html`（离线双击即可）就能看到：每个版本的完成 / 进行中 / 待做 / 阻塞 / 已移出、
任务列表（按版本、状态、模块筛选）、工作项依赖图（谁卡着谁）、`src/agenticops` 的代码模块依赖图、
「不一致」面板和最近完成的提交。

| 文件 | 作用 |
|---|---|
| `docs/progress/tracker.yaml` | **唯一真源**：版本 / 阶段 / 任务 / 依赖 / 状态 / 证据，由人和 agent 维护 |
| `docs/progress/dashboard.html` | 生成产物，入库；不要手改 |
| `scripts/progress/build_dashboard.py` | 生成器（只用 Python 标准库 + PyYAML，不 import `agenticops`） |
| `tests/test_progress_dashboard.py` | 生成器测试 |
| `.github/workflows/progress-dashboard.yml` | CI：每次 push / PR 重建比对 |

## 怎么维护

1. 完成或改变一个任务的状态时，改 `tracker.yaml`：状态、`evidence`（文档路径、提交 SHA + 提交日期 + 标题），
   并把 `updated` 改成当天日期。
2. 重建并一起提交：

   ```bash
   python scripts/progress/build_dashboard.py          # 写 docs/progress/dashboard.html
   git add docs/progress/tracker.yaml docs/progress/dashboard.html
   ```

3. 每个状态都要有出处（发布说明、计划、提交）。查不到就写 `todo`，或在 `notes` 写「未从文档确认」，不要猜。

## 命令

| 命令 | 作用 | 退出码 |
|---|---|---|
| `build_dashboard.py` | 读 tracker + 仓库文件，写 `docs/progress/dashboard.html` | 0；tracker 校验失败 2 |
| `build_dashboard.py --check` | 重新生成并与入库页面比对，不写文件；过期时打印 diff 摘要 | 0 最新；1 过期 / 不存在；2 校验失败 |
| `build_dashboard.py --verify [--strict]` | git 一致性核对，只输出到 stdout：证据 SHA 是否存在、提交日期（committer date，`%cs`）是否等于 tracker 记录、填了 `title` 时是否等于提交标题（`%s`）、done 的条目有没有证据 | 默认 0（只告警）；`--strict` 有问题时 1 |
| `build_dashboard.py --watch` | 每秒轮询 tracker、`docs/**/*.md`、`src/agenticops/**/*.py`，变了就重建 | Ctrl-C 结束 |
| `build_dashboard.py --live [--out PATH]` | 写一份带 `<meta http-equiv="refresh" content="5">` 的页面到**仓库外**（默认 `/tmp/agenticops-progress-dashboard.html`；仓库内的路径会被拒绝，退 2）；可加 `--watch` 边改边看 | 0 |
| `--root DIR` | 指定仓库根（默认脚本所在仓库） | — |

入库的 `dashboard.html` 永远不带自动刷新。

**确定性**：页面只取决于仓库里的文件（tracker、它引用的文档、`src/agenticops` 源码），不嵌入当前时间、HEAD、分支或实时
`git log`，所以同一份文件两次生成逐字节相同，提交页面本身也不会让 CI 的 `--check` 失败。git 事实只出现在 `--verify` 的输出里。

## CI 在查什么

`.github/workflows/progress-dashboard.yml`（push 与 pull_request；`fetch-depth: 0`；Python 3.11；只装 `pyyaml pytest`）：

1. `pytest --noconftest tests/test_progress_dashboard.py -q`。要加 `--noconftest`：仓库根的 `tests/conftest.py` 会 import
   botocore 和 `agenticops`，这个 job 不装它们。
2. `build_dashboard.py --check`：改了 tracker、计划文档、RELEASE 文档或源码却没重建页面，job 失败。
3. `build_dashboard.py --verify`：结果写入 job summary，只告警。
4. 上传 `docs/progress/dashboard.html` 为 artifact。

## 校验（生成前，失败即退 2、不写任何文件，输出指明位置）

- `schema` 不是 1，或 `updated` 不是 `YYYY-MM-DD`；
- 版本或条目的状态不在枚举内；
- 条目 id 重复（跨版本也算）、版本 id 重复；
- `depends_on` 或 `moved_to` 指向不存在的 id；
- 工作项依赖成环（含自环）；
- `modules` 里的路径在 `src/agenticops` 下不存在；
- `status: moved` 缺 `moved_to`；
- 提交证据缺 `sha` / `date`，或格式不对。

## 核对项（不阻断，进页面的「不一致」面板；生成器从不改写 tracker）

| kind | 含义 |
|---|---|
| `plan_unchecked` | 条目 done，它的 `plan` 文档勾过至少一个框、却还有未勾选的 `- [ ]`（一个框都没勾的计划视为不用勾选框记进度，不报） |
| `plan_missing` | `plan` 指向的文件不在仓库里 |
| `release_mismatch` | tracker 状态与版本 `doc` 里阶段表（表头含「阶段」「状态」）的状态文字矛盾。按条目 id 最后一段（`2.7.0/S1` → `S1`）对行；已验收 / 已完成 / 已发布 ≈ done，未开始 ≈ todo，进行中 ≈ in_progress，移至 … ≈ moved |
| `release_unknown` | 「无法比对」：阶段表的状态文字读不出上面任何一种，不作猜测 |
| `blocked` | 条目 in_progress / todo / blocked，但有上游没完成（列出被谁卡住） |
| `no_evidence` | 条目 done，却没有任何 `evidence`（docs / commits） |
| `evidence_missing` | `evidence.docs` 里的路径不在仓库里 |

## 字段说明

```yaml
schema: 1
updated: "YYYY-MM-DD"        # 人或 agent 最后编辑的日期；生成器不读系统时钟
releases:
  - id: "2.7.0"              # 版本号，唯一
    title: "..."
    status: released         # released | in_progress | planned
    branch: MVP-2.7.0        # 可空
    tag: v2.7.0              # 可空
    doc: docs/MVP-2.7.0-RELEASE.md   # 可空；有阶段表时用来核对状态
    notes: "..."             # 可选，版本级说明
    items:
      - id: "2.7.0/S1"       # 全局唯一；最后一段与 RELEASE 阶段表的行首（S1、A1）对应
        title: "..."
        status: done         # done | in_progress | todo | blocked | moved | dropped
        depends_on: ["2.6.1/A"]      # 工作项依赖（上游 id）
        modules: ["services/verification", "web", "models.py"]  # 相对 src/agenticops：目录、.py 文件或省略 .py 的模块
        plan: docs/superpowers/plans/....md   # 可空；done 时核对勾选框
        evidence:
          docs: ["docs/MVP-2.7.0-RELEASE.md"]
          commits: [{sha: "33b8946", date: "2026-10-05", title: "..."}]  # date = 提交日期（%cs），title = 提交标题原文；生成器不现查 git，--verify 核对
        moved_to: "2.7.1/A1" # status=moved 时必填，必须是存在的 id
        notes: "..."         # 出处、无法确认的地方
```

- 完成率 = done / (总数 − moved − dropped)。
- 模块依赖图：`ast` 解析 `src/agenticops/**/*.py` 里的 `import agenticops.x`、`from agenticops.x import`、相对导入
  （函数体内的延迟导入单独计数为 lazy），聚合到顶层包与顶层模块（`services`、`graph`、`models.py`、`config.py`…）；
  边权 = import 语句数，同一模块内部的导入不算边；强连通分量标为环（红色）。**默认只画顶层导入**（模块加载时执行的；
  边权 = 顶层语句数，只有延迟导入的边不画，环只按顶层导入算）；勾选「含函数体内的延迟导入」切到全部导入的视图，
  环与「最重的 15 条边」随视图重算。节点上的数字 = 挂在该模块上的未完成
  （in_progress / todo / blocked）条目数；点击节点筛出挂在它上面的全部任务（没有就显示 0 条）。`ast` 解析不了的文件
  不计入，并在图旁列出文件名。
- 「最近完成」取 tracker 证据里的提交，按记录的日期倒序。

## 初始数据的来源（2026-10-21）

- 1.0.0 – 2.5.0：每个版本一条汇总条目，状态与日期取自各自的 `docs/MVP-*-RELEASE.md`，提交为首次加入该发布说明的提交。
  汇总条目的 `modules` 按发布说明的主题挑选，只作导航用。
- 2.6.0：按 `docs/superpowers/plans/2026-09-17-change-management-p1-{a,b,c}-*.md` 拆成 Plan A–C；2.6.1 按
  `2026-09-28-mvp-2.6.1-plan-{a..e}-*.md` 拆成 Plan A–E。计划之间的依赖没有在文档里找到，没有填。
- 2.7.0：S1–S7 与 A1–A4 的状态取自 `origin/MVP-2.7.0` 上的 `docs/MVP-2.7.0-RELEASE.md` 与路线图（tag `v2.7.0` = `a953e6b`）；
  main 上的同一文档只写到 S5，所以「不一致」面板里会列出 S5–S7、A1–A4 与 main 文档的矛盾，这是真实的文档滞后。
  阶段依赖取自路线图阶段表的「依赖」列。
- 2.7.1：只有 A1–A4（todo；A2→A1、A3→A1、A4→A1/A2/A3，出自路线图核心能力轨表）。2.7.1 其他尚未推送的本地工作由主人补。
