# 模型提供方：不再只绑 Bedrock（设计）

2026-11-25，MVP-2.9.0 分支。

## 你说的

- 11-25：「请增加底层不同来源的 LLM 的支持，LiteLLM、Subapi 等这样的平台，请同时支持这样的 Model Provider，不和 Bedrock 强绑定。」
- 之后又说：「请在 UI 前端给出对应配置的 UI，以及完成后端接口的开发；把 LiteLLM proxy、OpenRouter、vLLM、Ollama 等这些全部支持；并优化前端 UI，使交互更方便。」

## 意图

AgenticOps 的每一次模型调用现在都走 Amazon Bedrock，这件事要改成可以选：

- 一个 agent、一处直接调用，可以用任何一家提供方的模型；
- 好几家提供方可以同时在用；
- 管理员在页面上加、测、停用提供方，不改配置文件、不重启。

Bedrock 仍然是默认，现有的配置一行不改照样能用；它也可以被关掉，整套不用 Bedrock 也能跑（见「你后来定的」）。

## 现在的样子（读代码看到的）

| 地方 | 现在 |
|---|---|
| 9 个 agent 的建法 | `main`、`scan`、`detect`（两处）、`rca`、`sre`、`executor`、`reporter`，再加命令行换模型的地方，都直接 `BedrockModel(...)` |
| 能力开关 | `agents/preamble.py` 按 Bedrock 的模型 id 判断：提示缓存、两种思考写法、OpenAI 家族的推理字段、温度、附件能不能原样给模型看（`media_capabilities`） |
| 直接调用 | `preamble.converse_text` 用 Bedrock Converse。调用它的有：合并判断、诊断复核、翻译、关系图、安全建议、技能演进、SOP 升级、旧的 RCA 引擎、内容翻译 |
| 网页端 3 处 | 会话标题（`web/app.py`）、`summary_service`、已冻结的 `memory_service`，用 Anthropic 专有的 InvokeModel 请求体 |
| 知识库向量 | `kb/embeddings` 用 Bedrock 的 Titan |
| 模型列表 | `services/model_service` 从 Bedrock 列出来，给设置页的 Agent 模型表、对话页的模型选择、关系图模型的下拉框 |
| 价格、上下文窗口 | `config.token_cost_table`、`MODEL_WINDOW_DEFAULTS`，按模型 id 的子串匹配 |
| 出错的说法 | `chat/stream_errors` 认的是 Bedrock 的异常 |
| 就绪检查 | `services/readiness` 查 Bedrock |
| 增强后端 | Claude Code 用 Bedrock 的环境变量 |

Strands 1.64 自带的提供方里，`OpenAIModel` 可以指到任何 OpenAI 兼容的地址，`AnthropicModel` 可以指到任何 Anthropic 兼容的地址。它们要的 `openai`、`anthropic` 两个包现在都没有装。

## 目标

1. **三种协议**：
   - Bedrock：照旧；
   - OpenAI 兼容：LiteLLM proxy、OpenRouter、vLLM、Ollama、LM Studio、DeepSeek 等，以及 Sub2API 的 Chat / Responses 接口里能按 Chat Completions 调的那部分；
   - Anthropic 兼容：Anthropic 官方、Sub2API 的 `/v1/messages`。
2. **每个平台一个预设**：LiteLLM proxy、OpenRouter、vLLM、Ollama、LM Studio、Sub2API、Anthropic、自定义（OpenAI 兼容）、自定义（Anthropic 兼容）。预设填好协议和默认地址，管理员只填 Key 和要改的地方。
3. **所有文字模型调用都能换**：9 个 agent、`converse_text` 的每一个调用方、网页端的会话标题和摘要。
4. **模型列表**：
   - 从每个提供方读（OpenAI 兼容：`GET /v1/models`；Anthropic 兼容：`GET /v1/models`，读不到时手工添加）；
   - 和 Bedrock 的合在一起，给所有选模型的地方用。
5. **每个模型的属性**：
   - 能力：工具调用、图片、文档、推理 / 思考的写法；
   - 上下文窗口、最大输出；
   - 价格：不知道就记 0、标「未计价」。
   - 能从列表接口读到的就自动填（OpenRouter 的列表带价格和上下文长度，vLLM 带最大长度），其余管理员可以改。
6. **测试连接**：
   - 读模型列表；
   - 一次很短的对话；
   - 一次工具调用的探测——agent 离不开工具调用，本地模型不一定支持。
   - 结果和用时存下来，页面上显示。
7. **知识库向量可以换**：可以指到 OpenAI 兼容的向量接口（Ollama、vLLM、LiteLLM proxy）。换了模型，向量的维度会变，所以有一个「重建向量」的操作。默认仍是 Titan。
8. **页面**：
   - 设置里新加一页「模型提供方」；
   - Agent 模型表、对话页的模型选择、关系图模型的下拉框，换成同一个**可搜索、按提供方分组、带能力标记**的选择器；
   - 选了不支持工具调用的模型给 agent，当场提醒。

## 不做（这一次）

- 增强后端（Claude Code / Kiro / Codex）仍按现在的方式走。
- 已冻结的 `memory_service` 不动。
- 不把 Agent 模型的配置从 `settings.yaml` 搬进库里。你 11-08 定过要搬，那是另一件事。这一次模型引用照旧写在 `settings.yaml` 里，提供方本身在库里。
- 不做提供方之间的自动切换 / 兜底：一个模型调不通就报错，不悄悄换到别家。
- 不接 LiteLLM 这个库本身。LiteLLM 由它的 proxy（OpenAI 兼容）接入。

## 不能出现的情况（反目标）

- 现有只用 Bedrock 的部署：升级之后行为有任何变化。
- 一个提供方的 Key 出现在接口的返回、日志、审计行、页面上，哪怕一次。
- 调用失败时**悄悄**退回 Bedrock 或别的提供方。和账户凭证一样：失败就明说。
- 给 Bedrock 模型用的请求字段被发给别家（缓存点、思考字段），导致整次请求失败。现在 OpenAI 家族在 Bedrock 上就因为这个吃过亏。

## 约束

- **凭证规矩**：
  - Key 用现有的凭证加密（`credentials/store` 的加密后端：`AIOPS_MASTER_KEY` / KMS），不回显；
  - 编辑时照账户的规矩：密钥字段留空、回传掩码都保持不变，删 Key 要明说；
  - 增删改都写一行审计，只记非密钥字段和「Key 变没变」。
  - 没有配加密后端的地方（开发机现在就是），页面上照实写「Key 以明文存放」。
- **只有一个进程**；网络调用不放进 `async def` 里。
- **配置值不写死在 `config.py`**：默认值在 `settings.yaml`，运行时的改动在库里，照 `runtime_settings` 的样子。
- **能力判断只有一个地方**：Bedrock 的照旧按模型 id；别家的看模型的属性。
- **六个面逐行列清**：见下。

## 做法

考虑过三种：

| 做法 | 取舍 |
|---|---|
| **A. 按协议接，直接用 Strands 自带的提供方**（选这个） | 三种协议覆盖所有点名的平台；Claude 的缓存、思考在 Anthropic 兼容和 Bedrock 上原样保留；加两个包（`openai`、`anthropic`） |
| B. 非 Bedrock 的一律走 LiteLLM 库 | 一个入口接上百家，但依赖重、变得快；Claude 的功能要再经它翻译一层，出问题难查 |
| C. 只做 OpenAI 兼容 | 代码最少，但 Sub2API 的 Anthropic 接口和 Claude 的功能打折扣，算不上「全部支持」 |

选 A：怎么做由我来定（你说的是要什么），A 是唯一一个把点名的平台都接上、又不丢 Claude 功能的做法。

## 设计

### 1. 模型引用

- 一个模型写成 **`<提供方名>::<模型 id>`**，例如 `ollama-local::qwen3:32b`、`openrouter::anthropic/claude-sonnet-4.5`。
- 不带 `::` 的就是 Bedrock 的模型 id。所以现有的每一个 `agent_*_model_id`、`galaxy_model_id`、档位默认值、对话的模型选择**原样有效**。
- 用 `::`，是因为 Bedrock 的 id 和 ARN 里只有单个冒号，Ollama 的 `qwen3:32b` 也是，`/` 又出现在 OpenRouter 的 id 和 ARN 里。

### 2. 提供方存在库里

- 表 `model_providers`：
  - `name`：小写短名，唯一，用在引用里；
  - `display_name`；
  - `kind`：`openai_compatible` | `anthropic_compatible`；
  - `preset`；
  - `base_url`；
  - 加密的 `api_key`；
  - `extra_headers`（OpenRouter 要的 `HTTP-Referer` 之类，值按密钥处理）；
  - `timeout_seconds`；
  - `enabled`；
  - 最近一次测试的结果；
  - 时间戳。
- Bedrock 不进这张表。它是内置的那一家，区域和凭证照旧取自现有设置，页面上作为一行固定显示：不能删，可以关掉（`bedrock_enabled`）。
- 表 `provider_models`：每个提供方的模型。
  - 字段：`model_id`、`label`、`context_window`、`max_output_tokens`、`supports_tools`、`supports_images`、`supports_documents`、`reasoning`（`none` | `openai_effort` | `anthropic_thinking`）、四个价格（每百万 token：输入、输出、缓存读、缓存写）、`source`（`discovered` | `manual`）、`enabled`。
  - 「刷新列表」从提供方读；读到的模型更新属性，但管理员手工改过的字段不被覆盖。

### 3. 建模型只有一个入口

`agents/model_factory.build_model(ref, *, max_tokens, thinking_budget=0)`：

| 协议 | 建出来的 | 请求字段 |
|---|---|---|
| Bedrock | `BedrockModel` | 现在的 `bedrock_model_kwargs`（不动） |
| OpenAI 兼容 | `OpenAIModel(client_args={base_url, api_key, default_headers, timeout}, model_id, params)` | `max_tokens`；有推理能力的发 `reasoning_effort`（按预算换算档位，同现在的换算）；不发缓存点、不发思考字段 |
| Anthropic 兼容 | `AnthropicModel(client_args={base_url, api_key}, model_id, max_tokens, params)` | 思考的写法沿用现在按 Claude 版本的判断（≥ 4.6 用 adaptive + effort），有提示缓存时照 Bedrock 上的那一套 |

- 9 个建 agent 的地方和命令行换模型的地方都改成调它。
- `track_agent` 记的模型、价格、窗口都按引用取。

### 4. 直接调用

`preamble.converse_text(model_ref, …)` 的约定不变：

- 只在模型接受时发 `temperature`；
- 跳过推理块；
- 没有文字、或者在 `max_tokens` 处被截断，就抛 `ModelReplyError`。

按协议分到 Bedrock Converse / Chat Completions / Messages。会话标题和 `summary_service` 改用它，从此不再要求便宜档必须是 Claude。

### 5. 知识库向量

- 新设置 `embedding_model_ref`：空就是 Titan；指向一个 OpenAI 兼容提供方的模型，就用它的 `/v1/embeddings`。
- 换了模型、维度不同时，已有的向量不能再用：页面写明，「重建向量」重新算一遍（知识库现在只有 6 个案例）。

### 6. 价格、窗口、能力、出错的说法

- `cost.compute_cost`：Bedrock 照旧查价格表；别家的查 `provider_models` 的价格，没有就是 0、标「未计价」。
- 上下文窗口：Bedrock 照旧；别家的看 `context_window`，没有就用全局的默认值。
- `media_capabilities`、能不能带温度、推理写法：别家的看模型的属性。
- `chat/stream_errors`：认 `openai` / `anthropic` 的异常，映射到现有的几种说法：被限流、模型不可用、上下文太长、超时、请求被拒。

### 7. 接口

管理员才能写；有「看设置」权限的只读账户能读，Key 只显示掩码。

- `GET /api/model-providers`：列表，含内置的 Bedrock 一行、每家的模型数量、最近一次测试结果、加密后端是不是配了。
- `POST /api/model-providers`、`PATCH /api/model-providers/{id}`、`DELETE /api/model-providers/{id}`：
  - 有 agent 或设置正在用它的模型时，不能删也不能停用，返回 409，写明是谁在用；
  - 编辑照账户的合并规矩。
- `POST /api/model-providers/{id}/test`：读列表 + 一次短对话 + 一次工具调用探测，返回每一步的结果和用时。
- `POST /api/model-providers/{id}/refresh-models`、`GET /api/model-providers/{id}/models`、`PATCH /api/model-providers/{id}/models/{model}`（改属性、启用 / 停用）、`POST /api/model-providers/{id}/models`（手工添加）。
- `GET /api/settings` 的 `model_presets` 改成合并后的列表，每一项带 `provider`、能力、价格、窗口。
- `POST /api/kb/reembed`：重建向量。

### 8. 页面

- **设置 → 模型提供方**（新的一页）：
  - 每家一行：名字、协议、地址、模型数、状态（最近一次测试：通过 / 失败 + 原因 + 时间）、启用开关；
  - 「添加」先选平台（卡片：LiteLLM proxy、OpenRouter、vLLM、Ollama、LM Studio、Sub2API、Anthropic、自定义），再填表；预设把协议和默认地址填好；
  - 保存之前可以先点「测试连接」；
  - 每家的模型列表可以展开：搜索、改属性、启用 / 停用、手工添加；
  - 没有配加密后端时，页首一行提醒 Key 以明文存放。
- **模型选择器**（一个组件，三处用）：
  - 可以搜索，按提供方分组；
  - 每个模型带标记：工具、图片、文档、思考、未计价、窗口大小；
  - 停用的提供方 / 模型不出现；
  - 当前值不在列表里时照实显示「不在列表里」；
  - 给 agent 选了不支持工具调用的模型，旁边写明这个 agent 会用不了工具。
- **设置 → 知识库**：「向量模型」的选择和「重建向量」。

## 评审之后我定的（不对请改）

一位没看过的评审读了这份文档，下面四条是他问的、我能自己定的：

1. **用到模型的设置都能换，都能在页面上选**：
   - 除了 7 个 agent 和关系图，还有三个档位的默认值、执行器的简单模型（`executor_simple_model_id`）、安全建议（`security_model_id`）、报告翻译（`report_translation_model_id`），都接受 `提供方::模型`。
   - 设置页的 Agent 模型表下面加一张「其他用到模型的地方」，用同一个选择器，写回 `settings.yaml`，和 Agent 模型现在的保存方式一样。
2. **测试连接测的是一个模型**：
   - 管理员选一个（默认是这家第一个启用的模型；新加的提供方填一个模型 id）。
   - 工具调用的探测结果单独记在那个模型上（通过 / 失败 / 没测过 + 时间），不覆盖管理员手工设的值。
   - 「支持工具调用」有三种状态：是 / 否 / 没测过。新发现的模型是「没测过」，列表接口自己写明了的除外（OpenRouter 的 `supported_parameters` 里有 tools）。
   - 选择器上「否」会提醒，「没测过」显示一个中性的「未测」。
3. **「正在用」指设置**：
   - 任何一个 agent、档位、上面那几项设置、向量模型的设置引用了它。对话自己选过的模型不算。
   - 一个对话选的模型被停用或删掉之后，下一次发送明确报错：「这个对话的模型 X 已经不可用，请换一个」。不悄悄换。
   - 停用单个模型，也按同样的规矩查。
4. **向量**：
   - 换到别家的向量模型，只在本地 SQLite 的向量库上可以做。pgvector 和 S3 Vectors 的维度是建表时定的，这一次在页面和接口上都写明「不支持」。
   - 向量服务调不通时：记一条警告，知识库搜索照现在的样子只用关键词，不悄悄换别家的向量模型。
   - 换了模型、还没重建之前，向量搜索没有结果，只剩关键词。页面写明「需要重建」。
   - `embedding_model_ref` 的默认值写在 `settings.yaml`，改动存进库里（`runtime_settings`）。
   - `provider_models` 加一个 `purpose`（`chat` | `embedding`）。名字里带 `embed` 的模型默认是向量模型，管理员可以改。选择器只列对应用途的模型。

## 你后来定的

- **要能完全不用 Bedrock 整套跑起来**（11-25）。Bedrock 从「固定的那一家」变成可以不配、可以关掉的一家：
  - 设置 `bedrock_enabled`：默认值在 `settings.yaml`（`true`），改动存进库里，由管理员在「模型提供方」页上切换，有审计。
  - 关掉之后：不再调用 Bedrock 的任何接口（模型列表、就绪检查、Titan）。任何一处设置要是还指着 Bedrock 的模型（不带 `::` 的引用），就明确报错，写明是哪一处设置，并且不悄悄换到别家。页面上这些设置标红。
  - 就绪检查查的是设置里实际引用到的提供方；启动时只刷新开着的提供方的模型列表。
  - 向量：Bedrock 关掉、又没有设 `embedding_model_ref` 时，知识库只用关键词搜索，页面上写明。
  - 三个档位的默认值也可以指向别家。从零开始、没有 Bedrock 的部署：启动之后先在页面上加一家提供方，把档位和 agent 指过去。
  - 增强后端（Claude Code）仍是非目标：Bedrock 关掉时，它照现在的样子不可用。
- **直接在 MVP-2.9.0 上做，一次交付**（11-25）。
- **真实的端到端测试（我的提议，你没有选）**：
  - 在本机临时起一个 LiteLLM proxy，装在 `/tmp` 下的独立环境里，不进项目，背后接 Bedrock。它对外同时提供 OpenAI 兼容和 Anthropic 兼容（`/v1/messages`）两种接口，所以两条路都是真的请求、真的模型，不用你提供 Key。
  - 在 AgenticOps 里关掉 Bedrock 跑一遍：这正好证明「完全不用 Bedrock」时整套能跑——AgenticOps 自己一次都没有调 Bedrock。
  - 要再加 Ollama（装在这台 Mac 上，约 5 GB）或 OpenRouter（要你的 Key），说一声。
- **依赖**：`strands-agents[openai,anthropic]` 进核心依赖（不完全用 Bedrock 时它们是必需的）；`uv lock` 后重新导出 `requirements.txt`。

## 六个面

| 面 | 这一次 |
|---|---|
| CLI | **做**：`aiops providers list`、`aiops providers test <名字>`（只读和测试；增删改在网页上） |
| Web API | **做**：上面第 7 条 |
| Web UI | **做**：上面第 8 条 |
| Agent 工具 | 非目标：agent 不管提供方；agent 用到的模型照设置走 |
| 定时任务 | 非目标 |
| 通知 | 非目标 |

## 留给实现的人

- 预设的默认地址和每家要的特别请求头；
- 推理档位的换算细节；
- 列表接口返回格式的解析（各家略有不同）；
- 选择器的具体样子，照现有的蓝白界面；
- 测试用的假服务怎么搭（不连外网的测试：在本机起一个假的 OpenAI 兼容 / Anthropic 兼容服务）。

## 风险

| 风险 | 应对 |
|---|---|
| 本地模型的工具调用不稳 | 测试连接里探测工具调用；结果写在选择器上；不拦，只提醒 |
| 数据经第三方平台出去（OpenRouter、Sub2API 会看到提示词里的基础设施信息） | 加提供方是管理员的动作，有审计；页面上写明数据会发给这家 |
| 两个新依赖 | 只装 `openai`、`anthropic`，进 `requirements.txt` / `pyproject` 的可选组 |
| 现有 Bedrock 行为被改动 | 不带 `::` 的引用一律走原来的代码路径；现有测试全量跑；`test_strands_parity` 照旧 |
