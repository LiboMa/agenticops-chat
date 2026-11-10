# 便宜档换成 Claude Haiku 5.5（并清掉 .env 里钉死的默认档）实施计划

> 本文件路径原来放的是 peer 会话的「用户凭证 + 侧栏」计划；那份已原样提交在 `docs/superpowers/plans/2026-11-10-mvp-2.8.0-credentials-sidebar-plan.md`（6d3969a），这里被本计划覆盖，获批后会告诉 peer。本计划获批后另存为 `docs/superpowers/plans/2026-11-10-haiku-5-5-cheap-tier-plan.md`。

## Context

**刚做完的模型升级**（已上线 :8000）：detect / RCA / executor 从 Opus 5 换成 Opus 5.5，SRE 从 Fable 5.1 换成 Fable 5.2，每个都用真实调用验过；Fable 5.2 的价格和窗口已进代码（26e988d）。

**这一步**：主人选「Plan it next」，把便宜档从 Claude Haiku 4.5 换成 Claude Haiku 5.5。
- **为什么换**：便宜十倍（$0.10 / $0.50 对 $1 / $5 每百万 token，提示词 ≤ 100K 时），也更强。便宜档负责 Signal Gate 合并判断、RCA 复核、安全建议复核、报告翻译、对话标题、会话摘要。
- **为什么不能只改配置**：Haiku 5.5 默认要思考，回复的第一块可能是思考块，思考也占 `max_tokens`。现在的调用方会出这几种问题（探查结果）：
  - 对话标题（`web/app.py` `_generate_session_title`）：直接调 InvokeModel，读 `content[0]["text"]`，`max_tokens` 只有 30。换上去后标题会悄悄变成空。
  - 会话摘要（`web/summary_service.py`）：同样读 `content[0]["text"]`，会 `KeyError`，被吞掉，摘要不再写入。它还绕过了 Bedrock 会话，直接用 `boto3.client`。
  - `web/memory_service.py`：冻结代码，生产里没人调用，但同样读 `content[0]`。
  - 走 `converse_text` 的几处：思考块会被正确跳过，但 `converse_text` 发不出思考力度（effort），Haiku 5.5 就按默认的 medium 思考。
    - Signal Gate 合并判断和 RCA 复核：`max_tokens` 500。
    - 安全建议的逐条复核：300。
    - 这几处会经常被截断（`ModelReplyTruncated`），翻译也会更常出现「太长」。
- **顺带发现**：主检出的 `.env` 有一行 `AIOPS_BEDROCK_MODEL_ID=global.anthropic.claude-opus-4-6-v1`，`.env` 优先于 `settings.yaml`，所以线上默认档其实是 Opus 4.6，不是 yaml 里的 Sonnet 5.5。
  - 现在每个 agent 都写了自己的模型，影响不大；但任何回落到默认档的路径，例如 CLI 重置 agent 模型，都会跑 Opus 4.6。
  - CLAUDE.md 规定任何环境变量都不得钉死模型；开发机 11-07 也修过同一个问题。

**成功的标准**：
- 便宜档是 Haiku 5.5；
- 上面每个调用方在真实的 Haiku 5.5 上都拿到正确的文字结果（不空、不截断）；
- 线上 :8000 的三个档位都来自 `settings.yaml`；
- 测试和文档都已跟上。

## 做法

1. **`converse_text` 加一个可选的思考力度**：
   - 签名变成 `agents/preamble.converse_text(model_id, prompt, *, max_tokens, temperature=None, read_timeout=None, total_attempts=None, effort=None)`。
   - `effort` 取 `low|medium|high|xhigh|max`，其他值抛 `ValueError`。
   - 只有 `supports_adaptive_thinking(model_id)` 为真的 Claude 模型，才在请求里加 `additionalModelRequestFields={"output_config": {"effort": effort}}`；Haiku 4.5、OpenAI 模型一律不发。所以这个参数换到任何模型上都安全。
   - 这个字段已在 Bedrock 实测：Haiku 5.5 / Opus 5.5 / Sonnet 5.5 / Fable 5.1 / 5.2 / Opus 5 都接受。
   - 不用 `thinking: disabled`：Opus 5.5 / Sonnet 5.5 一律 400，调用方一旦把模型改成它们就会出错。
2. **每个便宜档调用方改成 `effort="low"`，并给思考留出余量**。`max_tokens` 只是上限，计费只按实际生成的 token，所以调大不多花钱。
   - `services/signal_gate._call_bedrock`（Signal Gate 合并判断和 RCA 复核共用）：默认 `max_tokens` 500 → 2000，发 `effort="low"`。
   - `security/advisor.py`：
     - 逐条复核从 300 → 2000；
     - 建议生成从 1500 → 4000；
     - 两处都发 `effort="low"`。
   - `services/content_rendering._call_model`（翻译）：发 `effort="low"`，长度公式不变。
   - 对话标题：`web/app.py` `_generate_session_title` 改用 `converse_text(settings.bedrock_model_id_cheap, …, max_tokens=1024, effort="low")`；失败照旧返回 `None`。
   - 会话摘要：`web/summary_service.SummaryService.generate_summary` 改用 `converse_text`（`max_tokens=2000`、`effort="low"`）。这样它也走 Bedrock 会话，不再直接 `boto3.client`。返回值和失败处理不变。
   - `web/memory_service.py` 的两处抽取：同样改用 `converse_text`（`max_tokens=2000`、`effort="low"`），只换调用，不动别的。它是冻结代码，但不换的话一旦有人调用就会坏。
   - Galaxy 不动：它的模型是 Opus 5.5，不走便宜档。
3. **配置**：
   - `config.py` 默认值、仓库的 `config/settings.yaml`、线上主检出的 `config/settings.yaml`（先备份）：`bedrock_model_id_cheap` 改成 `global.anthropic.claude-haiku-5-5`；`haiku` 别名改成 5.5；新增 `haiku-4-5` 别名，旧型号仍可手动指定；注释跟着改。
   - 前端 `pages/Settings.tsx` 里写死的「Haiku 4.5」备用预设改成 Haiku 5.5，动之前先和 peer 打招呼。
   - 主检出 `.env`：删掉 `AIOPS_BEDROCK_MODEL_ID` 那一行（先备份），默认档回到 yaml 的 Sonnet 5.5。
   - `.env.example`：去掉三行过时的模型变量（Sonnet 4.6 / Haiku 4.5 / Opus 4.6），注明模型在 `settings.yaml` 里配置。
4. **不在本次**（记为后续）：
   - CloudFormation 模板和 `aiops init` 向导仍会写模型环境变量；向导会跟着 `haiku` 别名写 5.5。它们属于部署面，单独处理。
   - 开发机仍跑 MVP-2.7.1，不在本次部署。

## 在哪里做、怎么不和 peer 撞车

- **在哪里做**：新开 worktree `.worktrees/haiku-5-5`，分支 `feat/haiku-5-5-cheap-tier`，从 `66ee2bb` 切出。
  - peer 正在 `.worktrees/mvp-2.8.0` 里做它的计划，它不碰 `config.py`、`settings.yaml`、`preamble`、标题、`summary_service`、`memory_service`。
  - 用显式路径提交。
- **测试**：直接在我的 worktree 里跑 pytest，用自己的临时库 `/tmp/aiops-haiku55-test.db`；照 `aiops-pytest.sh` 的做法，跑前备份、跑后恢复 `agent-memory/` 和 `skills/`。跑全量之前先告诉 peer。
- **上线**：把我的提交 cherry-pick 到 `.worktrees/serve-2.8.0`（:8000 用的固定检出），这样只带上 peer 已经完成的提交。之后告诉 peer 把这个分支并进 MVP-2.8.0，或者等它说可以时由我 cherry-pick 过去。
- **文档**：CLAUDE.md / README 只改模型那几行，尽早合并，避免和 peer 的文档改动冲突。

## 任务（每个都先写会失败的测试）

- **T1 `converse_text` 的 `effort`**：在 `tests/test_converse_helper.py` 里沿用现有的 Bedrock 会话 mock，断言：
  - Haiku 5.5 / Opus 5.5 带 `effort="low"` 时，请求里有 `additionalModelRequestFields.output_config.effort == "low"`；
  - Haiku 4.5 和 `global.openai.gpt-6-astra` 不带这个字段；
  - 不传 `effort` 时请求和原来一模一样；
  - 非法值抛 `ValueError`。
- **T2 走 `converse_text` 的调用方**：沿用 `tests/test_model_routing.py` 的写法（mock 回复的第一块是思考块），断言 Signal Gate 合并判断、RCA 复核、建议复核、建议生成、翻译：
  - 都发 `effort="low"`；
  - 都带新的 `max_tokens`；
  - 都拿到正确的文字。
- **T3 标题、摘要、记忆改走 `converse_text`**：
  - `test_chat_session_rename.py` 的标题 mock 从 `invoke_model` 换成 `converse`，并加一条「第一块是思考块时标题仍正确」；
  - `test_summary_service*.py` 和 `test_memory_service*.py` 的 mock 跟着换；
  - `test_summary_service_props` 原来断言 `max_tokens ≤ 500`，改成断言请求的 `maxTokens` 等于新常量；
  - 加一条「摘要用的是 Bedrock 会话，不是裸 `boto3.client`」。
- **T4 配置切换**：
  - `test_claude5_bedrock_models.py`：`test_tiers_carry_no_opus_4_6` 的便宜档、`test_aliases_present` 的 `haiku`（5.5）和 `haiku-4-5`；
  - `tests/integration/test_converse_live.py` 的在线清单加入 Haiku 5.5；
  - `.env.example` 去掉模型变量，并加一条测试扫 `.env.example`，里面不能出现 `AIOPS_BEDROCK_MODEL_ID*`；
  - `Settings.tsx` 的备用预设。
- **T5 文档**：
  - CLAUDE.md：删掉「便宜档必须是 4.7 之前的 Claude」这条限制；档位说明、配置表那一行；Galaxy 价格倍数改为约 40×；L2 判断和 `security_model_id` 两行。
  - `README.md` / `README_CN.md` 的同一行，同一提交改。
  - `docs/WORKFLOW.md` 提到 Haiku temp=0 的两处。
  - 发布说明的追加小节。

## 验证

1. 改动的测试文件全部通过，然后跑全量（先告诉 peer）。除了已知的 DNS 假失败，不能有新的失败。
2. **在线**（真实 Haiku 5.5，总共几美分）：
   - `pytest tests/integration/test_converse_live.py --run-integration`；
   - 一个一次性脚本，把每个调用方的真实函数各调一次：Signal Gate 合并判断（一对样例告警）、RCA 复核（一份样例 RCA）、安全建议复核、对话标题、会话摘要、一小段报告翻译。每个都要拿到非空、未截断、能解析的结果，并记下 token 数。
3. **上线 :8000**：
   - 备份并修改线上 `settings.yaml` 和 `.env`；
   - 把提交 cherry-pick 到 serve worktree，重启；
   - 检查 `/api/health`，并打印实际生效的三个档位：默认 Sonnet 5.5、便宜 Haiku 5.5、强 Opus 5.5。
4. 记进项目记忆，在最终说明里列出我做的决定和后续项。
