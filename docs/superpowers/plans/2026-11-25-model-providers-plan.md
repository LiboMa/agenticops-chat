# 模型提供方（不再只绑 Bedrock）实施计划


**Goal**：AgenticOps 的每一处模型调用都可以指向 Bedrock 之外的提供方；整套可以完全不用 Bedrock 运行；管理员在页面上管理提供方和模型。

**Architecture**：
- 新包 `src/agenticops/llm/`：提供方的存储、模型引用的解析、唯一的建模型入口、直接调用、模型列表与测试。
- 建模型用 Strands 自带的 `BedrockModel` / `OpenAIModel` / `AnthropicModel`。
- 现有的调用点只换入口，不改各自的逻辑；不带 `::` 的引用一律走原来的 Bedrock 代码。

**Tech Stack**：Python 3.12、FastAPI、SQLAlchemy、Strands 1.64（`[openai,anthropic]` 两个附加组件）、React + TanStack Query + Radix、vitest、pytest。

**Spec**：`docs/superpowers/specs/2026-11-25-model-providers-design.md`（`9e317ed`）。

## Context

你 11-25 说的：增加 LiteLLM、Sub2API 这类平台的支持，同时支持多个提供方，不和 Bedrock 强绑定；页面上要有配置的地方，后端接口做完，LiteLLM proxy、OpenRouter、vLLM、Ollama 都支持，前端交互要更方便。之后定了两件事：

- 要能完全不用 Bedrock 跑；
- 直接在 MVP-2.9.0 上一次交付。

读代码看到的：

- **9 处**直接建 `BedrockModel`：main、scan、detect ×2、rca、sre、executor、reporter、`cli/context`。
- **11 个直接调用点**（经 7 个包装）走 `preamble.converse_text`。
- **7 处**绕开它直接调 Bedrock：
  - 会话标题、`summary_service`、已冻结的 `memory_service`，用 Anthropic 专有的请求体；
  - `kb/embeddings` 用 Titan；
  - `model_service` 列模型；
  - `/api/health` 的 STS 检查；
  - Claude Code 的环境变量。
- **按 Bedrock 模型 id 写的地方**：价格（`cost.normalize_model_key`）、窗口（`MODEL_WINDOW_DEFAULTS`）、能力（`preamble.media_capabilities` / `accepts_temperature` / 思考写法）、出错的说法（`chat/stream_errors.classify`，只认 botocore 的错误码）。
- **附件按 `agent.model.config["model_id"]` 判断能力**（`chat/attachments/delivery.agent_model_id`、`budget_hook`）。

## Global Constraints

- **模型引用**：`<提供方名>::<模型 id>`，按第一个 `::` 分开；不带 `::` 的是 Bedrock 的模型 id。现有的每一个设置原样有效。
- **提供方名**：`^[a-z][a-z0-9-]{1,31}$`，`bedrock` 保留；创建后不能改名。
- **Key 的规矩**：
  - 不出现在任何接口的返回、日志、审计行、页面上；
  - 编辑照 `credentials/store.merge_credentials`：空、回传掩码都保持，删要用 `clear_api_key`；
  - 用 `get_credential_store().encrypt_credentials` 存；
  - 存 Key 的列要加进 `security/db_redaction._EXCLUDED_COLUMNS`。
- **不悄悄兜底**：提供方停用、删除、调不通、Bedrock 关掉时，明确报错并写明是哪一处设置，从不换到别家。
- **能力判断**：Bedrock 照旧按模型 id；别家的只看 `provider_models` 的属性。Bedrock 的缓存点、思考字段、推理字段从不发给别家。
- **只有一个进程**；`async def` 里不做阻塞的网络调用（路由用普通 `def`，或者 `asyncio.to_thread`）。
- **配置值**：默认值写在 `config/settings.yaml`，运行时的改动存进库（`runtime_settings`），`config.py` 只放结构。
- **提供方的写操作**：只有管理员（`require_authenticated_user(request, admin=True)`）。读：管理员，或者有 `can_view_settings` 的只读账户。
- **一份改动对应一条要求**：不顺手改别的。`memory_service` 不动；增强后端不动。

## Review Focus

1. **地址的写法**：带不带结尾的 `/`、写不写 `/v1`。预设带 `/v1`；结尾的 `/` 去掉，不替人补 `/v1`。测试：`http://h:4000/` 和 `http://h:4000` 建出来的客户端地址一样（任务 2）。
2. **引用里的 `::`**：`parse_ref("p::a::b")` → 提供方 `p`、模型 `a::b`；`parse_ref("::x")`、`parse_ref("P!::x")` 报错（任务 1）。
3. **回传掩码或空的 Key**：PATCH `api_key="****abcd"` 或 `""` 都保持原 Key；`clear_api_key: true` 删掉（任务 4）。
4. **很慢或卡住的提供方**（Ollama 第一次加载模型）：测试连接在 `timeout_seconds` 到了就返回「超时」，不挂住；对话里报 `timeout`（任务 3、5）。
5. **Bedrock 关掉时，对话自己选的是 Bedrock 模型**：下一次发送明确报 `model_unavailable`，写明原因，不换模型（任务 6）。

---

## 文件

| 新建 | 职责 |
|---|---|
| `src/agenticops/llm/__init__.py` | 包 |
| `llm/models.py` | 两张表：`ModelProvider`（`model_providers`）、`ProviderModel`（`provider_models`） |
| `llm/refs.py` | 引用的解析 / 拼写 |
| `llm/presets.py` | 9 个平台预设（协议、默认地址、要不要 Key、说明） |
| `llm/registry.py` | 提供方的增删改查、合并、审计、「正在用」检查、Bedrock 开关 |
| `llm/factory.py` | `build_model`：唯一建模型的地方 |
| `llm/direct.py` | 单轮调用（OpenAI 兼容 / Anthropic 兼容） |
| `llm/catalog.py` | 读模型列表、解析各家的格式、手工添加、属性 |
| `llm/probe.py` | 测试连接 |
| `llm/embeddings.py` | OpenAI 兼容的向量客户端 |
| `web/routers/model_providers.py` | 接口 |
| `tests/llm_fake_server.py` | 本机假服务（OpenAI 兼容 + Anthropic 兼容，可以设延迟、可以关掉工具调用） |
| 前端：`lib/modelRefs.ts`、`components/models/ModelPicker.tsx`、`components/settings/ModelProvidersTab.tsx`、`components/settings/ProviderDialog.tsx`、`components/settings/ProviderModelsDialog.tsx`、`components/settings/OtherModelsCard.tsx`、`hooks/useModelProviders.ts` | 见任务 8、9 |

要改的：`pyproject.toml`、`uv.lock`、`requirements.txt`、`config.py`、`config/settings.yaml`、`models.py`（`init_db` 导入新表）、`security/db_redaction.py`、`agents/preamble.py`、9 个建 agent 的文件、`cost.py`、`chat/stream_errors.py`、`chat/attachments/{delivery,budget_hook}.py`、`web/app.py`、`web/summary_service.py`、`services/{model_service,readiness}.py`、`kb/embeddings.py`、`cli/main.py`、`pages/Settings.tsx`、`components/chat/ModelSelector.tsx`、`components/settings/KBTab.tsx`、`lib/setup.ts`、`hooks/useSettings.ts`、`locales/{en,zh}.json`。

---

### 任务 1：依赖、两张表、引用、预设、提供方的存储

**Files**：`pyproject.toml`、`uv.lock`、`requirements.txt`；新建 `llm/{__init__,models,refs,presets,registry}.py`；改 `models.py`（`init_db` 里导入 `agenticops.llm.models`）、`security/db_redaction.py`、`config.py` + `config/settings.yaml`（新块 `model_providers: {bedrock_enabled: true, test_timeout_seconds: 30}`，结构 `ModelProvidersSettings`）。测试：`tests/test_llm_registry.py`。

**Interfaces（Produces）**：
- `refs.REF_SEP = "::"`
- `refs.ModelRef(provider: Optional[str], model_id: str)`，带属性 `is_bedrock`
- `refs.parse_ref(ref: str) -> ModelRef`，不合法抛 `ValueError`
- `refs.format_ref(provider: str, model_id: str) -> str`
- `presets.PRESETS: dict[str, Preset]`，`Preset(kind, base_url, needs_key: bool, label, notes)`。9 个键与默认地址：
  - `litellm_proxy`：`http://localhost:4000/v1`
  - `openrouter`：`https://openrouter.ai/api/v1`
  - `vllm`：`http://localhost:8000/v1`
  - `ollama`：`http://localhost:11434/v1`
  - `lmstudio`：`http://localhost:1234/v1`
  - `sub2api`：kind `anthropic_compatible`，无默认地址
  - `anthropic`：`https://api.anthropic.com`
  - `custom_openai`、`custom_anthropic`：无默认地址
- `registry.ProviderConfig`：冻结的 dataclass，字段 `name, display_name, kind, preset, base_url, api_key, extra_headers: dict, timeout_seconds: int, enabled: bool`。解密后的，只在进程内用。
- `registry.get(name) -> Optional[ProviderConfig]`，按 `updated_at` 缓存。
- `registry.list_public() -> list[dict]`：从不含 Key，只有 `has_api_key: bool`。
- 写操作：
  - `create(data: dict, actor) -> dict`
  - `update(name, data: dict, actor, *, clear_api_key=False) -> dict`
  - `delete(name, actor) -> None`
  - `set_enabled(name, enabled: bool, actor) -> dict`
  - `bedrock_enabled() -> bool`
  - `set_bedrock_enabled(enabled: bool, actor) -> dict`（`runtime_settings` 的键 `model_providers`）
- `registry.ProviderError(status, code, detail, extra=None)`，code 有：`invalid_name`、`name_taken`、`reserved_name`、`invalid_kind`、`invalid_base_url`、`not_found`、`in_use`。
- `registry.references(provider: str, model_id: Optional[str] = None) -> list[str]`：返回引用它的设置名。范围是 `agent_*_model_id`、三个档位、`executor_simple_model_id`、`galaxy_model_id`、`security_model_id`、`report_translation_model_id`、`signal_gate_llm_model`、`rca_critic_model_id`、`embedding_model_ref`，看的是生效的值。
- `registry.bedrock_references() -> list[str]`：生效值是 Bedrock 模型的那些设置。

**测试（先写，先看着失败）**：
- `test_parse_ref`：
  - `parse_ref("global.anthropic.claude-opus-5-5").is_bedrock`
  - `parse_ref("ollama-local::qwen3:32b") == ModelRef("ollama-local", "qwen3:32b")`
  - `parse_ref("p::a::b").model_id == "a::b"`
  - `"::x"`、`"P!::x"`、`"p::"` 抛 `ValueError`
- `test_create_stores_the_key_encrypted_and_never_lists_it`：
  - 库里那一行的列值里找不到 Key 的原文（配了 `AIOPS_MASTER_KEY` 时）；
  - `list_public()` 只有 `has_api_key: True`；
  - `get()` 解密回原文。
- `test_plaintext_backend_still_keeps_the_key_intact`：没有加密后端时，Key 不被数据库清洗换成 `[REDACTED-SECRET]`。
- `test_update_merges_like_accounts`：`api_key` 为 `""`、`"****abcd"`、不传时原 Key 不变；新值替换；`clear_api_key=True` 删掉；`base_url` 改了；`name` 不能改（`invalid_name`）。
- `test_names`：`bedrock` 报 `reserved_name`；重名报 `name_taken`；`Bad Name` 报 `invalid_name`。
- `test_base_url`：只收 `http(s)://`，结尾的 `/` 去掉（`http://h:4000/` 存成 `http://h:4000`）；`ftp://x` 报 `invalid_base_url`。
- `test_delete_and_disable_refuse_while_a_setting_uses_it`：
  - `settings.agent_main_model_id = "p::m"` 时，`delete("p")` 和 `set_enabled("p", False)` 都抛 `in_use`，`extra={"refs": ["agent_main_model_id"]}`；
  - 改走这一处设置之后能删。
- `test_every_write_is_audited_without_the_key`：每次增、改、删、启停、Bedrock 开关都写一行 `audit_logs`。`new_values` 里有 `api_key: "replaced"|"kept"|"added"|"removed"`，没有 Key 的原文。
- `test_bedrock_switch`：
  - 默认值来自 yaml（`true`）；
  - `set_bedrock_enabled(False)` 之后 `bedrock_enabled()` 为假，并写一行审计；
  - `bedrock_references()` 列出生效值是 Bedrock 的设置。

**步骤**：
1. 写上面的测试，跑，看着失败（`ModuleNotFoundError: agenticops.llm`）。
2. 依赖：`pyproject.toml` 改成 `strands-agents[openai,anthropic]>=1.64.0,<2.0.0`；`uv lock`；`uv export --all-extras --no-hashes --no-dev -o requirements.txt`；`uv pip install -r requirements.txt` 进 `.venv`。
3. 实现，跑到通过。
4. 故意改错检查，提交。

### 任务 2：建模型的唯一入口 + 单轮调用

**Files**：新建 `llm/factory.py`、`llm/direct.py`、`tests/llm_fake_server.py`；改 `agents/preamble.py`（`converse_text` 遇到带 `::` 的引用时交给 `llm.direct.complete_text`；`media_capabilities`、`accepts_temperature` 遇到引用时看模型属性）。测试：`tests/test_llm_factory.py`、`tests/test_llm_direct.py`。

**Interfaces**：
- Consumes：`registry.get`、`registry.bedrock_enabled`、`catalog.model_row(provider, model_id) -> Optional[ProviderModelView]`（任务 3 定义；这一项先用最小的查询实现，任务 3 补全）。
- Produces：
  - `factory.build_model(ref: str, *, max_tokens: int, thinking_budget: int = 0)`：返回 Strands Model，并在模型对象上设 `aiops_ref = ref`。
  - `factory.ModelProviderUnavailable(RuntimeError)`，带 `ref`、`reason`。reason 有：`bedrock_off`、`unknown_provider`、`provider_disabled`、`model_disabled`、`unknown_model`。
  - `factory.ref_of(model) -> Optional[str]`：读 `aiops_ref`，没有就读 `config["model_id"]`。
  - `direct.complete_text(ref, prompt, *, max_tokens, temperature=None, read_timeout=None, total_attempts=None) -> tuple[str, dict, str]`：和 `converse_text` 同一个约定——返回文字、`{"input","output"}`、停止原因；没有文字抛 `ModelReplyEmpty`，被截断抛 `ModelReplyTruncated`。
- 请求字段：
  - Bedrock：原来的 `BedrockModel(... **bedrock_model_kwargs(model_id, thinking_fields_for_budget(budget, max_tokens, model_id)))`，一字不改。
  - OpenAI 兼容：`OpenAIModel(client_args={base_url, api_key or "none", default_headers, timeout, max_retries: 2}, model_id, params={"max_tokens": n, **({"reasoning_effort": 档位} if reasoning == "openai_effort" and budget > 0 else {})})`。档位换算沿用 `preamble` 现有的预算 → 档位规则。
  - Anthropic 兼容：`AnthropicModel(client_args={base_url, api_key, default_headers, timeout}, model_id, max_tokens, params=thinking_fields_for_budget(...) or {})`。只在 `reasoning == "anthropic_thinking"` 时带思考字段。Claude 模型、并且 `bedrock_cache_enabled` 时带 `cache_config`（和 Bedrock 上同一个配置）。

**测试**：
- `test_bedrock_ref_builds_exactly_what_it_built_before`：`build_model("global.anthropic.claude-opus-5-5", max_tokens=1000, thinking_budget=4096)` 得到 `BedrockModel`，`config` 和改动前的建法逐键相同（直接比对 `bedrock_model_kwargs` 的结果）。
- `test_openai_compatible_sends_no_bedrock_fields`：不带缓存点和思考字段；`base_url` 是去掉结尾 `/` 的地址；`reasoning_effort` 只在模型属性 `openai_effort` 且预算 > 0 时出现。
- `test_anthropic_compatible_thinking_follows_the_claude_version`：`claude-sonnet-4-6` 用 adaptive；`claude-3-5-haiku` 用 `budget_tokens`；模型属性 `none` 时不带思考字段。
- `test_unavailable_is_explicit`：Bedrock 关掉、提供方不存在 / 停用、模型停用时，都抛 `ModelProviderUnavailable`，reason 对得上；没有一次退回到 Bedrock（打桩 `get_bedrock_boto_session`，断言没被调用）。
- `test_complete_text_against_the_fake_server`：在本机起假服务，两种协议都覆盖：
  - 返回文字和 token 数；
  - `finish_reason="length"` / `stop_reason="max_tokens"` 抛 `ModelReplyTruncated`；
  - 空文字抛 `ModelReplyEmpty`；
  - 中文原样往返；
  - 假服务延迟 3 秒、`read_timeout=1` 时 1–2 秒内抛超时。
- `test_converse_text_dispatches_by_ref`：带 `::` 的走 `direct`；不带的仍走 `bedrock-runtime` 的 `converse`（用打桩的客户端断言）。
- `test_media_capabilities_and_temperature_for_refs`：引用的能力取自模型属性；OpenRouter 上叫 `anthropic/claude-sonnet-4.5` 的模型，不因为名字里有 `claude` 就算能看文档。

**步骤**：先写测试 → 失败 → 实现 → 通过 → 故意改错 → 提交。

### 任务 3：模型列表与测试连接

**Files**：新建 `llm/catalog.py`、`llm/probe.py`；测试 `tests/test_llm_catalog.py`、`tests/test_llm_probe.py`（用假服务）。

**Interfaces（Produces）**：
- `catalog.ProviderModelView`，字段：`provider, model_id, label, purpose ("chat"|"embedding"), context_window, max_output_tokens, supports_tools (True|False|None), tools_probe ("passed"|"failed"|None), tools_probe_at, supports_images, supports_documents, reasoning ("none"|"openai_effort"|"anthropic_thinking"), price_input, price_output, price_cache_read, price_cache_write (每百万 token, Optional[float]), source ("discovered"|"manual"), enabled, manual_fields: list[str]`。
- 读写：
  - `catalog.refresh(provider: str, actor) -> {"added", "updated", "unchanged", "error"}`
  - `catalog.list_models(provider, *, purpose=None, enabled_only=False) -> list[ProviderModelView]`
  - `catalog.model_row(provider, model_id) -> Optional[ProviderModelView]`
  - `catalog.add_manual(provider, data, actor)`
  - `catalog.patch_model(provider, model_id, data, actor)`：写进 `manual_fields`，之后刷新不再覆盖这些字段
  - `catalog.all_presets(*, purpose="chat") -> list[dict]`：所有开着的提供方的启用模型，键见任务 6
- `probe.test(provider: str, model_id: Optional[str]) -> dict`：返回 `{list: {ok, count, ms, error}, chat: {ok, ms, error}, tools: {ok, ms, error}}`，结果存到提供方的 `last_test` 和那个模型的 `tools_probe`。

**解析规则**（假服务可以模拟每种格式）：
- 通用 `{"data":[{"id"}]}`。
- OpenRouter：`context_length`；`pricing.prompt` / `completion` 是每 token 的美元，乘 1e6；`supported_parameters` 里有 `tools` 就是 `supports_tools=True`；`architecture.input_modalities` 里有 `image` 就是 `supports_images=True`。
- vLLM：`max_model_len`。
- Anthropic `/v1/models`：`data[].id` / `display_name`。
- 名字里有 `embed` 的模型：`purpose="embedding"`。

**测试**：
- `test_refresh_parses_each_listing_shape`：四种格式各一组，断言上面的字段。
- `test_manual_fields_survive_a_refresh`：手工改了 `context_window` 再刷新，值不变；没改过的字段照列表更新。
- `test_listing_failure_keeps_the_models`：列表读不到时，已有的模型保留，返回 `error`。
- `test_probe_reports_each_step`：
  - 假服务会调工具时：三步都 ok，模型的 `tools_probe="passed"`；
  - 不会调工具时：`tools.ok=False`、`tools_probe="failed"`，管理员设过的 `supports_tools` 不变；
  - 延迟超过 `timeout_seconds` 时：在时限内返回「超时」；
  - Key 错误（假服务回 401）时：`list.error` 写明「认证失败」，不含 Key。

### 任务 4：接口 + 命令行

**Files**：新建 `web/routers/model_providers.py`（在 `web/app.py` 注册）；改 `cli/main.py`（`providers_app`：`list`、`test`）。测试：`tests/test_model_providers_api.py`、`tests/test_cli_providers.py`。

**接口**（写：管理员；读：管理员或 `can_view_settings`；都是普通 `def`）：
- `GET /api/model-providers`：
  - `{bedrock: {enabled, region, references}, providers: [...list_public], presets: [...PRESETS], credential_backend}`
  - 每个提供方带 `models_count`、`last_test`、`references`
- `POST /api/model-providers` → 201；`PATCH /api/model-providers/{name}`（可带 `clear_api_key`）；`DELETE /api/model-providers/{name}`。
- `PUT /api/model-providers/bedrock {enabled}`：返回 `bedrock_references`，前端用它标红。
- `POST /api/model-providers/{name}/test {model_id?}`
- `POST /api/model-providers/{name}/refresh-models`
- `GET /api/model-providers/{name}/models?purpose=`
- `POST /api/model-providers/{name}/models`
- `PATCH /api/model-providers/{name}/models/{model_id:path}`
- 错误用 `{"detail": {"detail", "code", ...extra}}`，同 `web/routers/users._refused`。
- 写完清掉缓存的对话 agent：照 `model_runtime_settings._rebuild_chat_agents`。

**命令行**：
- `aiops providers list`：每家一行，名字、协议、地址、模型数、最近一次测试，不显示 Key；
- `aiops providers test <名字> [--model M]`：打印三步的结果，失败时退出码 1。

**测试**：
- `test_crud_round_trip_and_masking`：返回里从不出现 Key 的原文，包括 `json.dumps(response)`。
- `test_writes_need_an_admin`：写者 / 只读账户 / 只读的 API Key 写操作都是 403；带 `settings_read` 的只读账户能读。
- `test_delete_in_use_is_409_with_refs`
- `test_bedrock_switch_returns_the_settings_that_point_at_it`
- `test_test_route_uses_the_fake_server`
- `test_cli_list_and_test`：`CliRunner`；`test` 打到假服务；失败时退出码 1。

### 任务 5：所有调用点走新入口

**Files**：
- 9 个建 agent 的地方：`agents/{main,scan,detect,rca,sre,executor,reporter}_agent.py`、`cli/context.py`。
- `chat/attachments/{delivery,budget_hook}.py`：读 `factory.ref_of(agent.model)`。
- `cost.py`：引用查 `provider_models` 的价格，没有价格就是 0，不报警告。
- `config.get_agent_window_size`：引用用 `bedrock_window_size`，除非这个 agent 自己设了窗口。
- `chat/stream_errors.py`：认 `openai` / `anthropic` 的异常和 `ModelProviderUnavailable`。
- `web/app.py` 的会话标题、`web/summary_service.py`：改走 `converse_text`。
- `/api/health`：Bedrock 关掉时 `aws` 那一项写 `skipped`，不调用 STS。

测试：`tests/test_llm_call_sites.py`；`tests/test_strands_parity.py` 照旧通过。

**规则**：
- 每处把 `BedrockModel(...)` 换成 `build_model(model_id, max_tokens=…, thinking_budget=…)`。思考预算照原来的算法，main、rca 传，其余是 0。
- 原来就读 `get_agent_model_config` 的地方不改。

**出错的说法**：
- `RateLimitError` → `throttled`
- `APITimeoutError`、`httpx.ReadTimeout` → `timeout`
- `AuthenticationError`、`PermissionDeniedError`、`NotFoundError`、`APIConnectionError`、`InternalServerError`、`ModelProviderUnavailable` → `model_unavailable`
- `BadRequestError`：消息里有上下文相关的字眼 → `context_too_long`；其余 → `request_rejected`，`rejection_detail` 取它的 message
- `ModelProviderUnavailable` 的 detail 写明是哪个模型、为什么（例如「这个对话的模型 X 已经不可用，请换一个」）

**测试**：
- `test_no_bedrock_model_is_built_outside_the_factory`：扫 `src/`，`BedrockModel(` 只出现在 `llm/factory.py`。
- `test_every_agent_build_goes_through_build_model`：把 7 个 agent 照产品的建法建出来（打桩 `build_model`，记下引用和预算）；引用等于 `get_agent_model_config` 的值；main / rca 带预算。
- `test_attachments_read_the_ref`：OpenRouter 上的 `anthropic/claude-sonnet-4.5`，属性写的是不能看文档 → 文档变成文字。
- `test_cost_of_a_ref`：有价格时按价格算，没有时是 0；Bedrock 照旧。
- `test_stream_errors_for_other_providers`：上面每种异常各一条。
- `test_titles_and_summaries_use_converse_text`：便宜档设成假服务上的模型时，标题和摘要都能生成；不再调用 InvokeModel。
- `test_health_skips_bedrock_when_it_is_off`

### 任务 6：模型列表合并、设置、Bedrock 关掉、就绪检查

**Files**：`services/model_service.py`（`get_model_presets`：Bedrock 开着才列它；再接上 `catalog.all_presets()`）、`web/app.py`（`GET` / `PATCH /api/settings`、会话模型的校验、对话发送前的检查）、`services/readiness.py`。测试 `tests/test_settings_model_refs.py`。

**Interfaces（Produces）**：
- `model_presets` 的每一项：`{label, value, context_window, provider ("bedrock"|名字), provider_label, purpose, capabilities: {tools: true|false|null, images, documents, reasoning}, priced: bool}`。原来的 3 个键不变。
- `GET /api/settings` 新增：
  - `model_settings`：`{tier_default, tier_cheap, tier_strong, executor_simple, security, report_translation, signal_gate, rca_critic, galaxy}`，每项 `{value, effective, default}`；
  - `model_issues`：`[{setting, value, reason}]`，即生效值指向停用 / 删除 / 关掉的提供方的设置。
- `PATCH /api/settings` 新增 `model_settings`：
  - 映射到 `bedrock_model_id`、`bedrock_model_id_cheap`、`bedrock_model_id_strong`、`executor_simple_model_id`、`security_model_id`、`report_translation_model_id`、`signal_gate_llm_model`、`rca_critic_model_id`、`galaxy_model_id`；
  - 写回 yaml；有审计；清掉对话 agent。
  - 带 `::` 的值必须是开着的提供方的启用模型，否则 400 `unknown_model`；Bedrock 关掉时，不带 `::` 的值是 400 `bedrock_off`。
  - `agent_models.model_id` 同样校验（原来不校验）。
  - 只有管理员能改这些字段。原来写者也能改 `agent_models`——这一处收紧，在发布说明里照实写。
- 会话模型（`PATCH /api/chat/sessions/{id}`）：`_allowed_model_ids` 接上引用。发送时 `create_main_agent` 抛 `ModelProviderUnavailable` → 流里一帧 `error {code: model_unavailable, message}`，消息存成失败。
- 就绪检查：查 Main 的引用。引用的是别家时，`model.provider` 写名字，「验证」走 `direct.complete_text`。

**测试**：
- `test_presets_merge_and_skip_bedrock_when_off`：关掉时一次 Bedrock 控制面的调用都没有（打桩断言）。
- `test_patch_model_settings_validates_refs_and_writes_yaml`
- `test_agent_models_patch_needs_an_admin_now`
- `test_model_issues_lists_settings_pointing_at_a_disabled_provider`
- `test_chat_send_with_an_unavailable_model_fails_explicitly`：流里有 `model_unavailable` 和原因；没有建出任何 Bedrock 模型。
- `test_readiness_verifies_a_ref_main`

### 任务 7：知识库向量可以换

**Files**：新建 `llm/embeddings.py`（`OpenAICompatibleEmbedding(provider, model_id)`，`dimension` 由第一次调用得出）；改 `kb/embeddings.get_embedding_client`。改后的选择顺序：
1. `embedding_model_ref` 带 `::` → 走 OpenAI 兼容的向量接口；
2. 否则 Bedrock 开着 → Titan，并改用 `get_bedrock_boto_session()`，不再直接 `boto3.client`；
3. 否则 → `NullEmbeddingClient`。

接口加在 `web/routers/model_providers.py`：`GET /api/kb/embedding`（模型、维度、向量数、要不要重建）、`PUT /api/kb/embedding {model_ref}`、`POST /api/kb/reembed`（只在 SQLite 向量库上可以做；`rds` / `s3` 返回 409 `unsupported_store`）。设置项 `embedding_model_ref`：默认值进 yaml（`""`），改动存进 `runtime_settings`。

测试 `tests/test_llm_embeddings.py`：
- 假服务的 `/v1/embeddings` 返回向量；
- 换模型之后 `needs_reembed=True`，重建之后为假，`case_vectors` 的行数等于案例数；
- 向量服务调不通时，记警告并照旧只用关键词搜索；
- Bedrock 关掉、又没有设引用时，客户端是 Null，没有 Bedrock 调用；
- `rds` 时重建返回 409。

### 任务 8：前端——「模型提供方」一页

**Files**：
- 新建 `hooks/useModelProviders.ts`、`components/settings/{ModelProvidersTab,ProviderDialog,ProviderModelsDialog}.tsx`、`lib/providerForm.ts`；
- 改 `pages/Settings.tsx`（新 tab `providers`）、`lib/setup.ts`（`SETTINGS_TABS` 加 `providers`）、`locales/{en,zh}.json`（`settings.providers.*`）。

测试 `__tests__/providerForm.test.ts`；`setup.test.ts` / `settingsPage.test.ts` 跟着改。

**页面**：
- 页首：Bedrock 一行（开关、区域、还引用它的设置）。没有加密后端时，一行黄色提醒「Key 以明文存放」。
- 表格：名字、协议、地址、模型数、最近一次测试（通过 / 失败 + 原因 + 时间）、启用开关、操作（测试、模型、编辑、删除）。
- 「添加」：
  - 先选平台（9 张卡片，取自接口返回的 `presets`），再填表；
  - 表单项：名字、显示名、地址（预设填好）、Key（`needs_key` 为假时可以留空）、额外请求头（每行 `名字: 值`）、超时；
  - 保存前可以「测试连接」，填一个模型 id。
- 编辑：Key 一栏显示「已保存（****）」，留空就保持；有「删除已保存的 Key」。
- 模型对话框：
  - 搜索、按用途筛选、「刷新列表」、手工添加；
  - 每行：启用开关、能力标记（工具：是 / 否 / 未测）、窗口、价格（「未计价」）；
  - 点开可以改属性，手工改过的字段带一个点。
- 删除、停用被引用时，用接口给的 `refs` 写明是哪几处设置在用。
- 只读账户：整页在 `<fieldset disabled>` 里。
- 弹出层：`ModalFrame`（滑入、ESC）。

**`lib/providerForm.ts`**：
- `validateProviderForm(form) -> {field, reason} | null`：名字的规则、地址的规则、要 Key 时没有 Key；
- `headersFromText(text) -> Record<string,string> | {error}`；
- `patchFromForm(before, form) -> body`：只带改了的字段；Key 留空就不带。

测试覆盖这三个函数的每一条规则。

### 任务 9：前端——一个模型选择器，用在每一处

**Files**：
- 新建 `lib/modelRefs.ts`、`components/models/ModelPicker.tsx`、`components/settings/OtherModelsCard.tsx`；
- 改 `pages/Settings.tsx`（Agent 模型表、关系图模型卡换成 `ModelPicker`，加 `OtherModelsCard`）、`components/chat/ModelSelector.tsx`（列表部分用 `lib/modelRefs` 分组，标记一致）、`components/settings/KBTab.tsx`（向量模型 + 重建）、`hooks/useSettings.ts`（类型）。

测试 `__tests__/modelRefs.test.ts`；`chatDisplay.test.ts` 跟着改，它原来钉住的那几条不变。

**`lib/modelRefs.ts`**：
- `parseRef(value) -> {provider: string | null, model: string}`，和后端同一条规则；
- `groupPresets(presets, {purpose, query}) -> {provider, label, items}[]`：Bedrock 在前，其余按名字排；搜索匹配 label、id、提供方，不分大小写；
- `badges(p) -> string[]`：取 `tools` / `toolsUnknown` / `images` / `documents` / `reasoning` / `unpriced`；
- `issueOf(value, presets, modelIssues) -> "unavailable" | "noTools" | null`。

**`ModelPicker`**：
- props：`{value, presets, onChange, purpose, emptyOption?: {label}, requireTools?: boolean, disabled?, ariaLabel}`；
- 实现：Radix Popover + 输入框（`role="combobox"`）+ 分组列表（`role="listbox"` / `group` / `option`）；键盘用 `lib/menuNav.nextMenuIndex`；
- 当前值不在列表里时，显示「不在列表里」；
- `requireTools` 且模型的工具调用为「否」时，选择器下方写「这个 agent 会用不了工具」；
- `model_issues` 里有这一处设置时标红，并写明原因。

**`OtherModelsCard`**：`model_settings` 的 9 项，每项一行：名字、说明、`ModelPicker`（「默认」= 空）、生效的值。

**测试**：
- `parseRef` 的边界，和后端同一组例子；
- 分组的顺序；搜索；
- 每种标记；
- `issueOf` 的三种结果。

### 任务 10：真实的端到端、门禁、文档

**真实的端到端**：
- 起 LiteLLM proxy：在 `/tmp/nf-litellm` 里用独立环境装 `litellm[proxy]`，不进项目。
  - 配置两个模型：`claude-sonnet` → Bedrock 上的 Claude Sonnet，`titan-embed` → Bedrock 上的 Titan 向量模型；
  - 设一个只在本机用的 master key，存在 `/tmp/nf-litellm/key`（0600）；
  - 端口 :4000。
- 起 AgenticOps：一个临时实例（:8080，复制预览的副本库到 `/tmp`，不碰 :8001），加两家提供方：
  - `litellm-openai`：OpenAI 兼容，`http://localhost:4000/v1`；
  - `litellm-anthropic`：Anthropic 兼容，`http://localhost:4000`。
- 关掉 Bedrock，把 Main、便宜档、向量都指过去。逐项跑：
  1. 两家的测试连接，三步都要通过；
  2. 一轮对话：Main 用工具读本地库，问「列出账户和最近的问题」；
  3. 会话标题生成；
  4. 一次合并判断，走便宜档、Anthropic 兼容那一家；
  5. 重建向量，再搜一次案例；
  6. 一次检测——只读，账本旁边开着监视，见到不是「被拒绝」的写命令就停；
  7. 浏览器里走一遍新的一页和选择器（中英文、只读账户、ESC）。
- 证明 AgenticOps 自己没有调 Bedrock：
  - 进程日志里没有 `bedrock-runtime` 的请求；
  - 打开 boto 的调试日志，`bedrock-runtime` / `bedrock` 的请求计数为 0；
  - 所有模型请求都在 LiteLLM proxy 的日志里。
- 费用：LiteLLM 背后是 Bedrock，几美元以内。

**门禁**：
- 后端全量 `pytest tests/`；
- 前端在 `/tmp` 的干净副本里 `npm ci`、`tsc`、`build`；工作区里跑 vitest 全部。

**文档**：
- `docs/MVP-2.9.0-RELEASE.md` 新加一节（N35），写明行为变化：写者不再能改 Agent 模型，要管理员；新增两个依赖。
- `docs/MVP-2.9.0-E2E-REPORT.md`：端到端的数字。
- `docs/WORKFLOW.md`：新加一节「模型提供方」（怎么加 Ollama / LiteLLM proxy / OpenRouter / vLLM / Sub2API，怎么完全不用 Bedrock）。
- `CLAUDE.md`：`llm/` 一行；架构里「分档模型」那一段。
- 两份 README：2.9.0 那一行的末尾，同一个提交；不动白皮书会话引用的那两句。

**推送**：提交只用显式路径，`git push --no-verify`，推到 `origin/MVP-2.9.0`。
**部署到开发机**：先备份、看磁盘余量。开发机照旧用 Bedrock，提供方是可选的。

## 六个面

| 面 | 这一次 |
|---|---|
| CLI | **做**：`aiops providers list`、`aiops providers test <名字> [--model]` |
| Web API | **做**：任务 4、6、7 的接口 |
| Web UI | **做**：「模型提供方」一页；所有选模型的地方用一个选择器；「其他用到模型的地方」；知识库的向量模型 |
| Agent 工具 | 非目标：agent 不管提供方 |
| 定时任务 | 非目标 |
| 通知 | 非目标 |

## 验证

- 每项任务：新测试先失败、再通过；故意改错有测试变红。
- 改动前后，Bedrock 的建法逐键相同（任务 2 第一条测试）；`test_strands_parity` 照旧通过。
- 后端全量测试只剩已知的本机 DNS 假失败；前端单元测试全部通过；干净副本能构建。
- 真实的端到端（任务 10）：Bedrock 关掉时，两种协议、对话、标题、合并判断、向量、检测都走 LiteLLM proxy，AgenticOps 进程自己对 Bedrock 的请求为 0。
