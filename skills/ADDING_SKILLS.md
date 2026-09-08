# Adding New Agent Skills

This guide explains how to add a new domain skill to AgenticOps. Skills provide troubleshooting knowledge to the RCA and SRE agents — **no code changes required**.

## How It Works

```
skills/
├── your-skill-name/        ← directory name becomes the default skill name
│   ├── SKILL.md            ← REQUIRED: YAML frontmatter + decision trees
│   └── references/         ← OPTIONAL: deep-dive reference files
│       ├── topic-one.md
│       └── topic-two.md
├── linux-admin/
├── database-admin/
├── elasticsearch/
└── ...
```

The loader (`src/agenticops/skills/loader.py`) auto-discovers all subdirectories of `skills/` that contain a `SKILL.md` file. No registration, no config changes.

## Step-by-Step

### 1. Create the Skill Directory

```bash
mkdir -p skills/my-new-skill/references
```

Use kebab-case for directory names (e.g., `network-engineer`, `database-admin`).

### 2. Create `SKILL.md`

Every skill must have a `SKILL.md` file with YAML frontmatter:

```markdown
---
name: my-new-skill
description: "One-line description of what this skill covers — be specific about technologies, use cases, and failure modes. This text appears in the agent's system prompt (~100-200 chars is ideal)."
metadata:
  author: your-name
  version: "1.0"
  domain: infrastructure|data|networking|monitoring|security
---

# My New Skill

## Quick Decision Trees

### Problem Category 1

1. First diagnostic step: `command or API call`
2. If condition A:
   - Sub-step with explanation
   - Next check: `another command`
3. If condition B:
   - Different remediation path

**Escalation path:**

\```
Problem detected
  |
  +-- Condition A?
  |     +-- Sub-condition → action
  |     +-- Sub-condition → action
  |
  +-- Condition B?
        +-- Different path → action
\```

### Problem Category 2

(repeat pattern)

## Common Patterns

### Pattern Name

\```bash
# Useful commands grouped by scenario
command --with-flags
\```

## Key Metrics

| Metric | Warning | Critical | Notes |
|--------|---------|----------|-------|
| metric_name | > threshold | > threshold | context |
```

### 3. Add Reference Files (Optional)

Reference files provide deep-dive material loaded on demand via `read_skill_reference()`:

```bash
# Create reference files in references/ subdirectory
cat > skills/my-new-skill/references/topic-deep-dive.md << 'EOF'
# Topic Deep Dive

## Detailed procedures, command examples, and background knowledge
...
EOF
```

Reference files should be focused on a single topic (e.g., `mysql-diagnostics.md`, `pod-troubleshooting.md`). Keep each under 10KB for fast loading.

### 4. Verify

```bash
# Restart the server or CLI (skill cache is in-memory)
# Then verify the skill is discovered:
aiops chat "list available skills"

# Or via the API:
# The agent will call list_skills() and show your new skill

# Compile check (optional — no code changes, but good habit):
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'src')
from agenticops.skills.loader import discover_skills
skills = discover_skills()
for s in skills:
    print(f'  {s.name}: {s.description[:80]}...')
print(f'\nTotal: {len(skills)} skills')
"
```

## 从外部源导入技能（URL / git 仓库 / zip）

导入是**人类动作**，agent 没有导入工具。导入的技能一律落 draft——不注入提示词、不自动生效、包内脚本在导入过程中绝不被执行（没有 `install.sh` 之类的钩子）。

```bash
aiops skills import https://example.com/skill-pack.zip
aiops skills import git+https://github.com/org/repo.git@main#skills
aiops skills import ./bundle.tar.gz --name log-triage --name cost-digest
aiops skills import /path/to/local/skill-dir --json
```

一个仓库/归档里可以装多个技能：递归找出所有含 `SKILL.md` 的目录，每个视作一个包（命中后不再下钻，所以技能自己的
`references/SKILL.md` 不会被误当成第二个包）。`--name` 可按名过滤。

逐包硬约束（违反即该包被拒，其余包不受影响）：kebab-case 技能名、无符号链接、归档条目不得为绝对路径/含 `..`/为链接、
文件后缀在白名单内（**没有后缀的文件会导致整包被拒**——校验会逐个比对 `skills_import_allowed_extensions`）、
文件数 ≤ `skills_import_max_files`、总字节 ≤ `skills_import_max_package_bytes`。安装用 staging + 原子 rename，
所以不存在"装了一半"的技能。

Web 有两个入口：

- **页面**：Skills → Import → 「URL / Git 仓库」标签页，粘贴地址 → 导入。输入框下方会实时提示服务端将把它当成
  Git 仓库 / 压缩包链接 / 单个 SKILL.md / 服务器本地路径（与后端判定顺序一致，仅作提示）；展开「只导入指定技能」
  等价于 `--name`。导入后弹窗显示结果面板：已安装 / 已跳过 / 已拒绝三组，每条带后端给出的原因；已安装行点
  「查看并发布 →」进入草稿详情页做 Review / Promote。导入来的技能卡片上带 **Imported** 徽标，详情页显示来源、
  ref 与导入时间。「上传文件」标签页是原有的 `.md` / `.zip` 拖拽上传。
- **API**：`POST /api/skills/import-source`（`{"uri": ..., "names": [...]}`）；旧的 `POST /api/skills/import`
  仍是 multipart 文件上传那条路，两者不冲突。

导入后走既有审批链：

```
/skill review <name>     # 看 diff
/skill promote <name>    # 过整包安全扫描后才发布
/skill reject <name>     # 丢弃
```

`promote` 会扫整包（SKILL.md 正文 + 所有 `.sh`/`.py`）。两半是**同一道门的两种精度**，不是同一形状：`.py` 走 `ast`
并解析绑定（规则命中的是名字实际解析到的东西，所以 `model.eval()`／`df.eval()`／`session.exec()` 不再被误杀——这是
有意的取舍，代价是通过**无法解析**的接收者拿到的 `eval`/`exec` 也算干净）；`.sh` 仍是逐行匹配，所以散文里引用一条
blocked 命令也会被标出来。目录不存在、`.py` 解析失败都**fail-closed**。发现 blocked 级命令、读凭证文件、
`os.system`、`shell=True` 等即拒绝发布；旧版本自动进 `skills/.archive/`，可 `rollback`。

**诚实的说法**：这道门是人工 promote 前面的确定性预过滤器，不是对刻意混淆的抵抗。已知局限同源一处：`_py_prepass`
用 `ast.walk` 扫全树收集绑定，因此**不看可达性、不看作用域**——一条永远执行不到的语句仍会贡献绑定。

## 技能自带脚本与沙箱

技能包可以带 `*.py` / `*.sh`。它们**只能**被 `run_skill_script` 在受限沙箱里跑，且必须先 promote 成 published
（draft 直接拒跑）。

沙箱边界：
- **无凭证**——env 从空 dict 起建，只有 `PATH`/`HOME`/`LANG`，任何 `AWS_*` 结构上不可能出现；
- **无网络**——Linux 走 `unshare -n`，macOS 走 `sandbox-exec`；两者都拿不到时**直接拒跑**（默认），绝不假装隔离；
- **一次性工作目录**——脚本在临时目录里跑，跑完删除，写不回技能包；只有目标脚本本身被复制进去，所以包内同级文件
  在运行时**不存在**（`source`/`open()` 兄弟文件会失败）；
- **显式解释器**——按后缀查白名单，不看 shebang、不依赖可执行位、不起 shell（`.sh` 里放 python 代码就是喂给
  `/bin/bash`，反之亦然，这是有意的）；
- 超时 kill 进程组；stdout/stderr 各自截断到 `skills_sandbox_max_output_bytes`（**字节**，不是字符，CJK 输出要按
  字节预算算）。

**沙箱不限制文件系统写入**——脚本拥有服务账号的正常文件访问权。这正是整包安全扫描里那些"破坏性文件系统操作"规则
属于真实边界、而不只是纵深防御的原因。

因此脚本只适合**纯本地计算**：解析日志/JSON、统计、生成报表片段。需要云 API 的动作仍走
`run_aws_cli` / `run_on_host` / `run_kubectl` 的既有三级门。沙箱默认关闭，需在 `config/settings.yaml` 把
`skills_sandbox_enabled` 设为 `true`——关着的时候 executor agent 的工具表里根本不会出现 `run_skill_script`。

## YAML Frontmatter Reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Skill name used in `activate_skill("name")`. Defaults to directory name if omitted. |
| `description` | Yes | Appears in agent system prompt. Be specific — agents use this to decide when to activate. |
| `metadata.author` | No | Who wrote the skill. |
| `metadata.version` | No | Skill version. |
| `metadata.domain` | No | Category: infrastructure, data, networking, monitoring, security. |
| `license` | No | License identifier (e.g., "MIT", "Apache-2.0"). |
| `compatibility` | No | Compatibility notes (e.g., "strands-agents >= 1.0"). |

## How Agents Use Skills

The agent interaction follows a **progressive disclosure** pattern:

1. **System prompt** — `<available_skills>` XML lists all skills with names and descriptions (~100 tokens per skill). Agents see this automatically.

2. **`activate_skill("name")`** — Agent calls this when it needs domain knowledge. Loads the full SKILL.md body (decision trees, commands, patterns). ~3-5K tokens.

3. **`read_skill_reference("name", "references/file.md")`** — Agent calls this for deep-dive material on a specific topic. Loaded on demand.

```
System prompt:     ~100 tokens/skill  (always loaded)
activate_skill:    ~3-5K tokens       (loaded when needed)
read_skill_ref:    ~2-8K tokens       (loaded when needed)
```

## Agent Routing

Skills are available to these agents:

| Agent | Tools | Notes |
|-------|-------|-------|
| **RCA agent** | `activate_skill`, `read_skill_reference`, `run_on_host`, `run_kubectl` | Full investigation + execution |
| **SRE agent** | `activate_skill`, `read_skill_reference`, `run_on_host`, `run_kubectl` | Fix planning + investigation |
| **Main agent** | `list_skills`, `activate_skill`, `read_skill_reference` | Discovery + routing (no execution) |
| **Scan agent** | `activate_skill`, `read_skill_reference` | Dynamic tool registration for scans |
| **Detect agent** | `activate_skill`, `read_skill_reference` | Dynamic tool registration for health checks |

To add skill activation prompts to a new agent, update its system prompt in `src/agenticops/agents/` — see `rca_agent.py` step 1.5 for the pattern.

## Writing Good Decision Trees

Tips from existing skills:

- **Start with diagnostics, not fixes** — the first steps should gather data
- **Use specific commands** — agents will execute these via `run_on_host` or `run_kubectl`
- **Include escalation paths** — ASCII flowcharts help agents reason through branching logic
- **Add thresholds** — "CPU > 90% for 5+ minutes" is better than "CPU is high"
- **Reference CloudWatch metrics** — agents can check metrics via specialized tools
- **Separate read-only vs write operations** — read-only commands execute automatically; write commands require confirmation

## Config

| Setting | Default | Description |
|---------|---------|-------------|
| `AIOPS_SKILLS_DIR` | `PROJECT_ROOT/skills` | Path to skills directory |
| `AIOPS_SKILLS_ENABLED` | `true` | Set `false` to disable all skills |

## Existing Skills

| Skill | Domain | Description |
|-------|--------|-------------|
| `linux-admin` | infrastructure | Process, disk, memory, network diagnostics |
| `network-engineer` | networking | Routing, firewall, TCP, VPN, MTU |
| `kubernetes-admin` | infrastructure | Pods, nodes, CNI, CoreDNS, PVC, HPA |
| `database-admin` | data | RDS, DynamoDB, ElastiCache diagnostics |
| `elasticsearch` | data | Cluster health, DSL queries, JVM, ILM, snapshots |
| `monitoring` | monitoring | CloudWatch, Prometheus, SLI/SLO |
| `log-analysis` | monitoring | CloudWatch Insights, pod logs, error patterns |
| `aws-compute` | infrastructure | EC2, ECS, EKS, Lambda troubleshooting |
| `aws-storage` | infrastructure | S3, EBS, EFS, FSx troubleshooting |
| `web-research` | operations | Fetch public web data, status pages, CVE databases |
| `document-analysis` | operations | Read and analyze PDF, DOCX, CSV, XLSX documents |
