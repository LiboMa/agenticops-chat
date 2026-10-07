# MVP-2.6.1 图事实层实测

由 `scripts/measure_graph_facts.py` 生成（2026-09-30T02:06:33+00:00）。数据源 `/Users/malibo/MyDev/AgenticOps/data/agenticops.db` 以只读方式打开，经 SQLite backup API 复制。迁移、锚定回填、规则构建和查询都在副本上跑，原库不写。规则构建时 LLM 阶段换成了返回空边的桩：不调 Bedrock，零成本；查询层默认只读规则边（`include_llm=False`），所以测的就是它。

库存：2 个账户，1534 个资源。

## 锚定率（spec §8.1）

有 `resource_id` 的未关闭 Issue 共 888 条。(anchored + account_level) / 总数 = (562 + 25) / 888 = **66.1%**，目标 ≥ 95%：**未达标**。

| anchor_status | 条数 |
|---|---|
| anchored | 562 |
| account_level | 25 |
| ambiguous | 4 |
| unanchored | 297 |

未锚定的原因分布（`anchor_candidates.rule`）：

| anchor_status | rule | 条数 |
|---|---|---|
| unanchored | none | 291 |
| unanchored | account_unknown | 6 |
| ambiguous | resource_id | 4 |

`rule = none`（库存里找不到这个资源）按 id 形态的前 10 类：

| id 形态 | 条数 |
|---|---|
| `arn:cloudformation` | 39 |
| `arn:elasticloadbalancing` | 38 |
| `arn:iam` | 35 |
| `arn:rds` | 25 |
| `arn:ec2` | 18 |
| `arn:secretsmanager` | 18 |
| `arn:cloudfront` | 15 |
| `arn:apigateway` | 15 |
| `arn:ecr` | 12 |
| `other` | 12 |

按 spec §8.1，未达标时如实报告原因分布，**不放宽规则去凑数**。`none`：库存里没有这个资源，多为未扫描的资源类型；`unknown_account`：信号指向本平台未管理的账户；`account_unknown`：Issue 没有账户，也没有留下它的信号记录（已过保留期或从未写入），不跨账户去猜；`ambiguous`：同一条规则命中了多个物理资源，候选都记在 `anchor_candidates` 里。

## 跨账户重复 id（spec §8.1）

库存里有 36 组跨账户重复的 `resource_id`，指向它们的未关闭 Issue 有 0 条。其中锚到错误账户 0 条，没有账户却被锚定 0 条。

不限重复 id，有声明账户的未关闭锚定 Issue 共 553 条（声明账户在回填前读出：Issue 自身的 `account_id`，为空时取它最早一条 promoted 信号的 `alert_events.account_id`），锚点落在别的账户的 0 条（应为 0）。

`resolve()` 探测：不给账户时锚定 0 次（应为 0）；给出持有账户时 72/72 次锚定，其中锚到别的账户 0 次（应为 0）。结论：**达标**。

## 查询性能（spec §7、§8.2）

规则构建 build #18 耗时 1.7 秒，发布关系 rule 781 条、llm 0 条（LLM 阶段是桩，应为 0）。

对 457 个锚定资源各做 3 轮 2 跳 `neighborhood`，每次调用前清缓存（测未命中路径），共 1371 次。SQL 条数最多 4（目标 ≤ 5）；耗时 p50 4.1 ms、p95 6.1 ms、最大 43.3 ms（目标 p95 < 200 ms）；最大邻域 76 个节点，截断 0 次。结论：**达标**。
