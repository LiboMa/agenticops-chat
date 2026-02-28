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
