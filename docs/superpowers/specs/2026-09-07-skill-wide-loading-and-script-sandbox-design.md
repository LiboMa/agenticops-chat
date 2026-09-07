# 技能广域加载 + 脚本沙箱 设计（Skill Wide Loading & Script Sandbox）

**日期：** 2026-09-07
**状态：** 设计已批准（主人 2026-09-07 确认路线 A 及全部安全默认值），待实施
**上位约束：** `CLAUDE.md`（凭证安全铁律、config.py 不硬编码、简约高性能经济）；永久安全铁律——AWS 凭证 / 密码 / AK·SK / session token / 私钥**绝不落盘、绝不入 Memory**

## 1. 目标

让技能（Agent Skills）能从**更广的来源**装载，并允许技能包自带**可执行脚本**在受限沙箱中运行：

1. **三条摄入源**：`http(s)://` URL（zip/tar.gz 包，或裸 `SKILL.md`）、git 仓库（含大仓多技能、`@ref` 与 `#subdir`）、zip 归档（远程或本地）。
2. **多技能仓自动发现**：递归找出所有含 `SKILL.md` 的目录，每个视作一个技能包，可按名过滤。
3. **脚本沙箱**：技能包内 `*.py` / `*.sh` 可被 agent 调用执行，但只在**无凭证、无网络、临时工作目录、超时受限**的隔离子进程中运行。

### 非目标（明确不做）

- 不做技能包签名 / commit-sha pin 锁定（供应链防偿改留待后续；本期以"一律人类审批"替代）。
- 不做容器化执行、不做目标主机（SSM）执行技能脚本——沙箱只在本机子进程内。
- 不给 agent 导入技能的工具：**导入是人类动作**。
- 不改 `loader.py` 的发现/注入逻辑，不改三层渐进披露，不改提示词预算。
- 不给沙箱脚本任何 AWS 凭证或网络（因此技能脚本用途限于：解析日志/JSON、统计分析、生成报表等纯本地计算；需要云 API 的动作仍走既有 `run_aws_cli` / `run_on_host` / `run_kubectl` 三级门）。

## 2. 现状与接缝（已核实）

- 技能 = 目录 `skills/<name>/SKILL.md` (+ `references/*.md`)，由 `loader._scan_directory` 扫 `settings.skills_dir`（published）与 `settings.skills_draft_dir`（draft）发现，draft 打 `is_draft=True` 且**不注入系统提示词**。
- `registry.py` 已有 `SkillRegistry` 抽象（`search`/`install`）+ `LocalRegistry` + 占位 `ClawHubRegistry`。
- `review.promote_skill(name)`：draft → published，途中调 `security.scan_skill_safety(body)`（仅扫正文 fenced bash），并把既有 published 版本归档到 `skills/.archive/<name>__<ts>/`（多代可回滚，`rollback_skill`）；`reject_draft_skill` 丢弃 draft。
- `security.py`：`classify_shell_command` / `classify_kubectl_command` 三级分类（blocked/write/readonly/unknown）+ `SHELL_BLOCKED_PATTERNS` + `_SKILL_DESTRUCTIVE_PATTERNS`。
- `loader._validate_skill_name`：kebab-case 校验 + 路径穿越守卫。
- 执行现状：只有 `execution.run_on_host`（SSM→SSH 阶梯）与 `run_kubectl`，**没有任何"跑技能自带脚本"的路径**。

**结论：** 本设计在既有接缝上做增量——摄入接 `drafts + promote + .archive` 这套已验证的审批/回滚机制，执行则新开一个与之正交的受限通道。

## 3. 架构

```
uri ──fetch──> 临时目录 ──discover──> [含 SKILL.md 的目录…]
                                        │ 逐包：名字校验 / 路径穿越 / 符号链接 / 体积 / 文件类型白名单
                                        ▼
                            staging → 原子 rename → skills_draft_dir/<name>/   ← 仅落盘，未生效
                                        │ 人类 review（list_draft_skills / review_draft_skill）
                                        ▼
                            promote（scan_skill_bundle 门）→ skills_dir/<name>/  ← 生效
                                        │ agent activate_skill
                                        ▼
                            run_skill_script → sandbox（隔离 / 无凭证 / 无网络 / 超时）
```

### 文件清单

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/agenticops/skills/sources.py` | 新增 | `fetch` / `discover_packages` / `install_packages` / `import_skills` 门面 |
| `src/agenticops/skills/sandbox.py` | 新增 | `run_script` 受限执行器 + 隔离器探测 |
| `src/agenticops/skills/security.py` | 扩展 | 新增 `scan_skill_bundle(pkg_dir)`、`_PY_DESTRUCTIVE_PATTERNS` |
| `src/agenticops/skills/review.py` | 改 | `promote_skill` 由 `scan_skill_safety(body)` 改为 `scan_skill_bundle(pkg_dir)` |
| `src/agenticops/skills/tools.py` | 扩展 | 新增 agent 工具 `run_skill_script`（仅 published） |
| `src/agenticops/skills/curator.py` | 改 | 老化判定由 `created_by == "agent"` 放宽为 `in ("agent", "imported")`（人类手写的 `user` 仍钉住不动） |
| `src/agenticops/config.py` | 扩展 | 9 个新 schema 字段（仅 schema，无硬编码值） |
| `config/settings.yaml` | 扩展 | 上述字段的默认值 |
| `src/agenticops/cli/main.py` | 扩展 | `aiops skills import <uri> [--name N]...` |
| `src/agenticops/web/app.py`（或对应 router） | 扩展 | `POST /api/skills/import` |
| `tests/test_skill_sources.py` | 新增 | 摄入层测试（hermetic） |
| `tests/test_skill_sandbox.py` | 新增 | 沙箱测试（hermetic） |
| `tests/test_skill_bundle_scan.py` | 新增 | bundle 扫描测试 |

`loader.py` 不动。

## 4. 摄入层 `skills/sources.py`

### 4.1 接口

```python
@dataclass
class ImportedSkill:
    name: str
    path: Path            # 落盘后的 draft 目录
    files: int
    bytes: int

@dataclass
class ImportResult:
    source_uri: str
    source_ref: str                       # git commit sha / zip sha256 / url，仅作溯源记录（不做 pin 校验）
    installed: list[ImportedSkill]
    skipped: list[tuple[str, str]]        # (name, reason) —— 已存在同名 draft 等非安全原因
    rejected: list[tuple[str, str]]       # (name-or-path, reason) —— 安全/校验拒绝

def import_skills(uri: str, names: list[str] | None = None) -> ImportResult: ...
def fetch(uri: str, workdir: Path) -> tuple[Path, str]: ...        # -> (解包后的根目录, source_ref)
def discover_packages(root: Path) -> list[Path]: ...
def install_packages(pkgs: list[Path], source_uri: str, source_ref: str,
                     names: list[str] | None = None) -> ImportResult: ...
```

### 4.2 `fetch` 的源识别（按顺序判定，首个匹配生效）

| 形态 | 判定 | 动作 | `source_ref` |
|---|---|---|---|
| `git+https://…`、以 `.git` 结尾、`github.com/<org>/<repo>` 形态 | 前缀/后缀/主机模式 | `git clone --depth 1 [--branch <ref>]`；`#subdir` 则把根定位到该子目录 | `git rev-parse HEAD` |
| `http(s)://…` 且后缀或 `Content-Type` 指示归档（`.zip`/`.tar.gz`/`.tgz`） | 后缀优先，其次 Content-Type | 下载到临时文件 → 解包 | 归档内容 `sha256` |
| `http(s)://…` 且内容为 markdown（后缀 `.md` 或 `text/markdown`/`text/plain`） | 同上 | 视为**单技能包**：新建 `<tmp>/<name>/SKILL.md`，`name` 取 frontmatter 的 `name`，缺失则取 URL basename（再过名字校验） | 内容 `sha256` |
| 本地路径 `.zip`/`.tar.gz` | `Path.exists()` | 解包 | 文件 `sha256` |
| 本地目录 | `Path.is_dir()` | 直接作为根 | `"local-dir"` |
| 其它 | — | `ValueError("unsupported skill source: …")` | — |

**下载与解包硬约束**（任一违反即整源拒绝，抛错）：

- 下载总字节 ≤ `skills_import_max_package_bytes`（流式累计，超限即断）。
- 归档解包前逐条目校验：条目名 normalize 后不得为绝对路径、不得含 `..`、不得是符号链接/硬链接/设备文件；解压后总字节 ≤ 上限；条目数 ≤ `skills_import_max_files`。**不使用** `ZipFile.extractall` 的默认行为兜底，逐条目显式校验后再写。
- `git clone` 用 `subprocess`（`shell=False`），`--depth 1`，超时 `skills_import_timeout_seconds`；clone 后删除 `.git` 目录再进流水线。
- 全流程只写系统临时目录（`tempfile.mkdtemp`），函数返回前清理。

### 4.3 `discover_packages`

递归遍历 `root`：目录内存在 `SKILL.md`（大小写敏感）→ 记为一个包，**不再下钻其子目录**；跳过 `.git`、`__pycache__`、`node_modules`、`.archive`、以 `.` 开头的目录。返回按路径排序的列表（确定性）。根目录本身也参与判定（单技能包情形）。

### 4.4 `install_packages` 逐包校验（fail-closed，拒绝即记 `rejected` 并继续下一个）

1. **技能名**：优先 `SKILL.md` frontmatter 的 `name`，缺失则用目录名；过 `loader._validate_skill_name`（kebab-case + 路径穿越守卫）；不在 `names` 过滤集中 → 记 `skipped`（非拒绝）。
2. **冲突**：`skills_draft_dir/<name>` 已存在 → 记 `skipped`（不覆盖，要更新先 reject 旧 draft）；`skills_dir/<name>` 已存在（published 同名）→ 记 `skipped` 并在原因中提示用 `improve_skill`/先 rollback。
3. **文件白名单**：包内每个文件后缀必须在 `skills_import_allowed_extensions` 内；不允许符号链接；不允许任何解析（`Path.resolve()`）后落在包根之外的路径；单包文件数 ≤ `skills_import_max_files`、总字节 ≤ `skills_import_max_package_bytes`。违反 → 整包 `rejected`。
4. **落盘**：先写 `skills_draft_dir/.staging/<name>-<uuid>/`，全部文件写完后 `os.replace` 原子 rename 到 `skills_draft_dir/<name>/`（无半装状态）；脚本文件写入时**不置可执行位**（沙箱显式指定解释器，不依赖 shebang）。
5. **provenance frontmatter**（复用 `normalize_skill_frontmatter` 后追加）：`created_by: imported`、`source_uri`、`source_ref`、`imported_at`（ISO8601）、`skill_version`、`status: active`。`created_by=imported` 与既有 `user`（人类钦定、Curator 永不动）/`agent`（可老化归档）并列——**`imported` 按 `agent` 同等对待**（可被 Curator 老化归档，因为它同样不是主人手写的）。
6. 全部包处理完 → `_invalidate_skills_cache()`。

### 4.5 摄入不做的事

不注入提示词（drafts 天然不注入）、不自动 promote、不执行任何包内代码、不解析或执行 `install.sh` 之类的安装钩子（**明确禁止**：包内脚本只能事后经沙箱按需调用）。

## 5. 安全扫描 `security.scan_skill_bundle`

```python
def scan_skill_bundle(pkg_dir: Path) -> dict:
    """返回 {'safe': bool, 'findings': [{'file','line','snippet','tier','reason'}]}"""
```

- `SKILL.md`：沿用现有 `scan_skill_safety(body)`（fenced bash 逐条过 `classify_shell_command` + `_SKILL_DESTRUCTIVE_PATTERNS`）。
- `*.sh`：逐行剥注释与空行，每条命令过 `classify_shell_command`；`blocked` → finding（`safe=False`）。
- `*.py`：过新增 `_PY_DESTRUCTIVE_PATTERNS`（确定性正则，零 LLM）——至少覆盖：
  - `os.system` / `subprocess.*` 调用中出现 blocked 级命令模式；
  - 读取凭证文件：`~/.aws/credentials`、`~/.aws/config`、`.ssh/id_`、`/etc/shadow`；
  - 从环境捞凭证外传：出现 `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` / `os.environ` 与 `requests`/`urllib`/`socket` 同现；
  - `shutil.rmtree("/")` 类破坏性调用、`eval`/`exec` 于下载内容。
- 其它后缀（`.md`/`.txt`/`.json`/`.yaml`/`.csv`）不扫（非可执行）。
- `promote_skill` 在 `settings.skills_security_scan_on_promote` 为真时调用它，`safe=False` → 拒绝 promote 并回报 findings（保持现有返回契约：`bool`；findings 走日志 + `review_draft_skill` 输出）。

**定位**：这是**辅助闸门**，不是可证安全的分析器。真正的边界是沙箱（无凭证、无网络）+ 人类审批。设计上不假设扫描器能识别混淆代码。

## 6. 沙箱 `skills/sandbox.py`

### 6.1 接口

```python
@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    duration_ms: int
    isolation: str          # 'unshare' | 'sandbox-exec' | 'none'

def run_script(skill_name: str, script: str, args: list[str] | None = None,
               stdin_text: str | None = None) -> SandboxResult: ...

def detect_isolation() -> str: ...   # 探测可用隔离器，缓存结果
```

### 6.2 执行契约（逐条都是硬要求）

1. **只跑 published**：`skill_name` 必须解析到 `skills_dir/<name>`（经 `_validate_skill_name` + resolve 后确认在 `skills_dir` 之内）。draft → 拒绝（`RuntimeError`）。
2. **脚本路径**：`script` 是包内相对路径，resolve 后必须仍在该技能目录内（路径穿越守卫），且后缀在 `skills_sandbox_interpreters` 的键中。
3. **解释器白名单**：`.py` → `sys.executable`；`.sh` → `/bin/bash`。**不看 shebang、不依赖可执行位、`shell=False`**。
4. **零凭证环境**：env 从**空 dict 起建**，只注入 `PATH`（固定安全值 `/usr/bin:/bin`）、`HOME`（指向一次性工作目录）、`LANG`。不继承 `os.environ`，因此任何 `AWS_*` / `AIOPS_*` / 代理变量结构上不可能出现。
5. **网络隔离**：Linux → `unshare -n --`；macOS → `sandbox-exec -p '(version 1)(allow default)(deny network*)'`；两者都不可用时——若 `skills_sandbox_require_isolation` 为真（默认）→**拒跑并明确报错**，为假 → 跑但在 `SandboxResult.isolation='none'` 与日志中显式标注"未隔离"。绝不谎称隔离。
6. **一次性工作目录**：`tempfile.mkdtemp()` 作为 `cwd`；脚本与（可选）`stdin_text` 写入其中；跑完无条件递归删除。技能目录本身**不作为 cwd**，脚本不能就地写回技能包。
7. **资源限制**：`timeout=skills_sandbox_timeout_seconds`（超时 kill 进程组，`exit_code=-1`，`stderr` 记超时）；stdout/stderr 各截断至 `skills_sandbox_max_output_chars`（`truncated=True`）。
8. **总开关**：`skills_sandbox_enabled` 为假（默认）→ 工具直接返回"沙箱未启用"，不起进程。

### 6.3 Agent 工具

`tools.run_skill_script(skill_name, script, args="", stdin_text="")` → 格式化的 `SandboxResult` 文本。挂在与 `activate_skill` 同一批工具里（scan/detect/main 等已有 skills 工具的 agent），受 `skills_sandbox_enabled` 门控。

## 7. 入口

- **CLI**：`aiops skills import <uri> [--name N ...] [--json]` → 打印 `installed/skipped/rejected` 三段与逐条原因；退出码：全部失败 1，部分成功 0。
- **Web**：`POST /api/skills/import`，body `{uri: str, names?: [str]}` → `ImportResult` 的 JSON；已有的 draft review / promote / reject / rollback 端点无需改动即可接管后续流程。
- **Agent**：无导入工具（人类动作）。仅新增 `run_skill_script`。

## 8. 配置（`config.py` 只加 schema，值进 `config/settings.yaml`）

| 字段 | 默认 | 说明 |
|---|---|---|
| `skills_import_enabled` | `true` | 关闭时 CLI/API 入口直接拒绝 |
| `skills_import_max_package_bytes` | `2097152`（2 MiB） | 单包解包后总字节上限，也用作下载上限 |
| `skills_import_max_files` | `50` | 单包文件数上限 |
| `skills_import_allowed_extensions` | `[".md",".py",".sh",".txt",".json",".yaml",".yml",".csv"]` | 文件类型白名单 |
| `skills_import_timeout_seconds` | `60` | 下载 / `git clone` 超时 |
| `skills_sandbox_enabled` | `false` | 脚本沙箱总开关（新执行通道，默认关，显式开启才生效） |
| `skills_sandbox_timeout_seconds` | `60` | 单次脚本执行超时 |
| `skills_sandbox_max_output_chars` | `20000` | stdout/stderr 各自截断上限 |
| `skills_sandbox_require_isolation` | `true` | 拿不到 `unshare -n` / `sandbox-exec` 就拒跑 |
| `skills_sandbox_interpreters` | `{".py": "python", ".sh": "/bin/bash"}` | 后缀 → 解释器白名单（`"python"` 解析为 `sys.executable`） |

## 9. 错误处理

- **逐包 fail-soft**：一个包被拒不影响其余；结果三分类（installed / skipped / rejected）都带原因，调用方总能看清发生了什么。
- **安全 fail-closed**：任何校验或扫描违规 → 拒绝该包 / 拒跑该脚本，绝不"降级放行"。
- **整源级错误**（网络失败、`git clone` 失败、归档损坏、超体积）→ 抛出带原因的异常，不产生任何落盘副作用。
- **无半装状态**：staging + 原子 rename。
- **临时目录**：`try/finally` 无条件清理（含异常路径）。

## 10. 测试计划（全部 hermetic：零网络、零真实 AWS）

**`tests/test_skill_sources.py`**
1. 本地目录源：单技能包被发现并落 draft，frontmatter 带 `created_by=imported` / `source_uri` / `source_ref`。
2. 多技能仓（`git init` 造本地假仓 + `file://` 克隆或直接目录）：递归发现 3 个包全部落 draft。
3. `names` 过滤：只装指定的 1 个，其余记 `skipped`。
4. `discover_packages` 命中后不下钻（技能内 `references/` 含 `SKILL.md` 的构造不产生第二个包）。
5. zip 源：tmp 内现造 zip → 正常导入。
6. **拒绝面**：zip 条目含 `../escape/SKILL.md` → rejected 且磁盘上无越界文件；符号链接条目 → rejected；超 `max_files` → rejected；超 `max_package_bytes` → rejected；后缀不在白名单（如 `.so`）→ rejected；坏技能名（`Foo Bar`、`../x`）→ rejected。
7. 同名 draft 已存在 → `skipped`，原有内容未被覆盖。
8. 不支持的 uri → `ValueError`。
9. 导入过程**不执行**包内任何脚本（放一个会写标记文件的 `install.sh`，断言标记文件不存在）。

**`tests/test_skill_bundle_scan.py`**
10. 干净包（只有 `SKILL.md` + 只读命令的 `.sh`）→ `safe=True`。
11. `.sh` 含 blocked 命令 → `safe=False` 且 finding 指向正确文件与行。
12. `.py` 读 `~/.aws/credentials` → `safe=False`；`.py` 里 `AWS_SECRET_ACCESS_KEY` + `requests` 同现 → `safe=False`。
13. `promote_skill` 对含 blocked 脚本的 draft **拒绝 promote**，draft 仍在原处；对干净 draft 正常 promote 且旧版本进 `.archive/`。
13b. Curator 老化：`created_by=imported` 的未用 draft 会随 `agent` 一同 `active→stale→archived`；`created_by=user` 的人类技能仍完全不受影响。

**`tests/test_skill_sandbox.py`**
14. `skills_sandbox_enabled=false` → 工具不起进程、返回未启用。
15. **环境零凭证**：脚本打印全部环境变量 → 断言输出中无任何 `AWS_`/`AIOPS_`/`SECRET`/`TOKEN` 键，且键集合 ⊆ `{PATH, HOME, LANG}`。
16. draft 技能 → 拒跑；脚本路径穿越（`../../etc/passwd`）→ 拒跑；后缀不在白名单（`.rb`）→ 拒跑。
17. 超时脚本（`sleep 999`）→ 被杀、`exit_code=-1`、时长 < 超时+余量。
18. 大量输出 → `truncated=True` 且长度 ≤ 上限。
19. exit code 透传（脚本 `exit 3` → `exit_code==3`）；stdout/stderr 分离正确。
20. `require_isolation=true` 且 `detect_isolation()` 打桩为 `none` → 拒跑并报错；打桩为可用 → 正常跑且 `isolation` 字段如实。
21. 工作目录一次性：脚本写文件 → 跑完该目录已不存在；技能目录未被写入。

## 11. 实施顺序（供 writing-plans 拆任务）

1. **配置层**：`config.py` schema + `settings.yaml` 值（无行为，先落地供后续引用）。
2. **摄入层**：`sources.py` 的 `discover_packages` → `install_packages`（含全部拒绝面）→ `fetch`（三源）；测试同步。
3. **扫描层**：`security.scan_skill_bundle` + `_PY_DESTRUCTIVE_PATTERNS`，改 `review.promote_skill`；测试同步。
4. **沙箱层**：`sandbox.py`（`detect_isolation` → `run_script`）+ `tools.run_skill_script`；测试同步。
5. **入口层**：CLI 子命令 + Web 端点。
6. **文档**：`CLAUDE.md` 的 skills 段落、`docs/WORKFLOW.md`、`skills/ADDING_SKILLS.md` 增"从外部源导入"与"脚本沙箱"两节。

## 12. 已定决策备忘（主人 2026-09-07 确认）

- 脚本处理方式＝**新增受限沙箱执行器**（而非只当资源读、也非复用 `run_on_host`）。
- 沙箱边界＝**本机子进程、无凭证、无网络**（不给只读凭证、不用容器、不下发到主机）。
- 导入门＝**一律 draft + 安全扫描 + 人类 promote 后才可用可跑**（不做来源 allowlist、不做内容 pin）。
- 包布局＝**自动递归发现所有 `SKILL.md`，可按名过滤**。
- 沙箱默认关闭；agent 无导入权。
- 断网无法用裸 `subprocess` 硬保证，故采取"**拿不到隔离器就拒跑**"，绝不给出假的"无网络"承诺。
