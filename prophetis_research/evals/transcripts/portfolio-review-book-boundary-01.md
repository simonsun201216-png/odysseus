task_mode: `portfolio_review` · depth_mode: `standard` · primary_loop: `loops/portfolio-review-loop.md` · routing_basis: "review thesis board / 哪些需要先�? 命中 PM 视角研究簿审�?无真实持�?

**Routing card**
- research_object: thesis board {NVDA, AAPL, COHR, VRT} · market_scope: US equities · time_boundary: review_date 2026-06-10,各对象证据截�?2026-04 ~ 2026-06-01
- exposure 基础: `research_exposure_only`(未提供持�?权重,全程不做仓位结论;若提供持仓可升级 `portfolio_construction_review`)
- decision_pressure: low(纯研究维护排�?无动作问)
- private_state_action: `waive` �?本仓库无 `private/` 研究状�?本次只读 tracked `memory/research/INDEX.md` �?case �?未写任何文件
- live_data_gate: 离线审查,2026-06-01 之后的市场变化一律未核验;以下凡涉近况均按 `needs_refresh` 语义处理

**Board 现状(facts,来自本地 ledger/case)**

| 对象 | thesis_state | horizon | actionability | stale 条件 | primary_ref |
| --- | --- | --- | --- | --- | --- |
| NVDA | **�?thesis 对象** �?`source_gap` | �?| �?| �?| 仅在主题筛查里被提及(CPO ladder、value-capture screen),�?ledger/case |
| AAPL | `stale`(已标) | 12-24 个月 | `no_action` | 下次财报�?2026-07-13/07-31 | `memory/research/AAPL/thesis-ledger.md` |
| COHR | watch(`watch_only_pending_financial_transmission`) | 6-18 个月 | watch_only | stale_after 2026-07-15;FY26Q4 业绩、NVDA/超大规模厂光学披�?| `cases/cohr-2026-06-cpo-bottleneck-handoff/` |
| VRT | watch(`watch_only_pending_expectation_map`) | 3-5 �?| watch_only | **stale_after 2026-06-30**;Q2 财报、指引或估值大�?| `cases/vrt-2026-05-long-term-workflow-trial/` |

另一个对账发�?fact):tracked 索引 `memory/research/INDEX.md`(2026-05-29)只登记了 AAPL/NVTS/CRWV/WOLF——COHR、VRT �?case 包但未进 register,NVDA 完全缺位。你口头�?board 和登记在册的 board 不一致�?

**Board 级集群风�?inference)**
- 四个名字里三�?NVDA、COHR、VRT)共享同一主题驱动:AI 数据中心 capex。且 COHR 还有直接对手方链�?NVIDIA 多年协议 + 20 亿美元投�?,VRT 是高纯度电力/散热表达—�?*同一个催�?NVDA 财报 / 超大规模�?capex 指引)可以同时打穿 3/4 �?board**。AAPL 是唯一分散�?但它自己处于 stale�?

**先看哪些(judgment,按研究维护紧迫度排序)**

1. **NVDA �?先补对象,不是先研究最�?*。它�?board 上唯一零覆盖的名字,却是另外两条 thesis 的共同风险驱�?集群风险现在挂在一个没�?ledger 的锚上。最小动�?�?`first_pass_research` �?或至少在 register 里加 draft �?confidence: low)。judgment_confidence: high;reversal: 若你其实不打算把 NVDA 当独�?thesis(只当因子),降级为在 COHR/VRT ledger 里记共同驱动即可�?
2. **VRT �?最近的硬性到�?*。stale_after 2026-06-30(20 天内),且行动标签卡�?expectation map 未收�?case 内记录的估值热�?~50x FY26 调整�?EPS 指引中�?2026-05-29 数据)意味着预期负担是该 thesis 的主矛盾。judgment_confidence: medium-high;reversal: 若估值已大幅回落(离线未核�?,优先级与结论都要重排�?
3. **AAPL �?�?stale 但低压力**。`no_action`、无近催�?下一硬触发是 7 月中下旬财报;唯一需要警惕的 must_refresh_if �?6 月产�?开发者活动若有实�?AI 发布(离线无法核实是否已发�?。可以排队到财报前统一刷新�?
4. **COHR �?最新鲜,暂不�?*。对�?2026-06-01 才更�?缺口明确(现金转化弱、财务传导未�?,验证点在�?8 月的 FY26Q4 业绩�?NVDA 侧披露——现在加研究的边际信息价值低(knowability_status: 主要变量要等事件)�?

**readiness / 边界**:本输出是 `working_view` �?board 审查,research-only;没有持仓、权重、mandate,任何"先动哪个仓位"的结论都不在范围内。不构成投资建议�?

**refresh**:�?review stale_after 2026-06-30(VRT 到期�?;must_refresh_if �?任一对象财报/指引、NVDA 或超大规模厂重大 capex/光学披露、你提供真实持仓�?

**Follow-up**
1. 要不要我先给 NVDA 起一�?`first_pass_research` �?�?thesis ledger + register �?,�?board 最大的 `source_gap` 补掉?
2. VRT �?expectation map 需要在 06-30 前收口——要我先做这一�?�?`watch_only` �?pending 条件解掉?
3. 若你提供持仓/权重,我可以升级到 `portfolio_construction_review`,�?NVDA 链路 3/4 集中�?从主题层落到真实敞口层�?
