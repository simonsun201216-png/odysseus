# Methodology Card: Thesis Horizon Routing

- status: trial
- role: framework-router
- last_updated: 2026-05-18
- source_bucket: `derived_internal`, `first_principles`
- source_quality: medium
- credibility_score: medium
- credibility_basis: 方法来自现有 Prophetis 框架、财报分�?skill 和研�?loop 的内部缺口整理；逻辑链清晰，但还需要更多真�?case 验证是否能稳定改�?memo 质量�?
- search_coverage: internal-only
- search_gaps: 尚未系统检索机构研究流程、buy-side 投资备忘录或卖方财报点评如何区分 1Q/FY1/长期 thesis�?
- comparison_baseline: `framework-routing` + `earnings-report-analysis` without explicit time-horizon routing
- empirical_validation_mode: live case trial
- follow_through_plan: 在后�?3-5 �?earnings case �?2 个首次覆�?case 中检查是否改�?thesis impact、refresh trigger �?long-term extrapolation 质量�?

## Core Idea

公司研究先判断结论的时间跨度，再判断定价 regime�?

财报分析主要解释 `1Q-4Q` �?`FY1/FY2` 的经营趋势和预期修正；一年以上的趋势需要额外分析产业、竞争格局、利润池、技术路径、资本配置和长期现金流曲线。单季财报可以验证或触发长期 thesis，但不能自动证明长期 thesis�?

## Reverse-Engineered From

- `skills/earnings-report-analysis/SKILL.md`
  已要求区分本期事实、指引�?-8 个季度预期变化、同行交叉验证和 thesis impact，并明确不能把单季波动自动外推成长期趋势�?
- `skills/equity-research-core/references/framework-routing.md`
  已要求先判断 pricing regime，但缺少时间跨度路由�?
- `loops/research-loop.md`
  已把 `thesis_horizon` 作为输入，但原流程没有把它转成证据权重和输出要求�?
- 用户提出的研究判断：
  财报分析偏短有效期，公司和板块趋势更适合一年以上的长期押注�?

## Search Paths Used

- internal artifact search:
  `earnings-report-analysis`, `framework-routing`, `research-loop`, `investment-memo template`
- functional gap search:
  查找现有文件�?`thesis_horizon` 是否只作为输入存在，还是已影�?routing 和输出字段�?
- derived internal comparison:
  对比财报 skill �?4-8 个季度逻辑�?equity core �?pricing regime 逻辑�?

## Use When

- 研究问题可能混合短期财报、未来几个季度盈利修正和一年以上产业趋势�?
- 用户问“这次财报是否改�?thesis”“长期值不值得押注”“短期趋势能否外推”�?
- 需要区�?`earnings impact`、`estimate revision` �?`long-term thesis change`�?
- memo 容易把好公司、好财报和好投资机会混成一个判断�?

## Avoid When

- 用户只要求整理事实，不要求判�?thesis�?
- 研究对象是纯宏观数据�?ETF 上市清单，不涉及单家公司时间跨度判断�?
- 证据不足以说明时间边界，只能输出低置信事实摘要�?

## Applies To

- `earnings-report-analysis`
  用于限制财报结论的外推范围�?
- `equity-research-core`
  用于�?framework routing 前先设定时间跨度�?
- `industry-concept-analysis`
  用于把产业长期趋势和单票短期兑现拆开�?

## Core Question

这个结论到底解释下一份财报、未来几个季度，还是一年以上的长期现金流和竞争格局�?

## Required Inputs

- `research_question`
- `thesis_horizon`
- 最新财报或事件是否是核心证�?
- FY1 / FY2 预期修正是否是核心变�?
- 长期产业、竞争、利润池或技术路线是否是核心变量
- 短期证据是否能被同行、客户、供应链、现金流或行业数据交叉验�?

## Primary Signal

- 结论能否明确落在 `near_term_execution`、`medium_term_revision`、`long_term_thesis` �?`regime_transition`
- 财报证据是否只影响季度节奏，还是影响长期变量
- 短期和长期信号冲突时，memo 是否降低结论强度而不是强行合�?

## Why It Works

投资研究的错误经常来自时间跨度错配：

- 把单�?beat 当成长期竞争力增�?
- 用长期故事忽�?FY1/FY2 下修
- 把普通季度波动误判为产业拐点
- 把真正的长期拐点降级成短期噪�?

显式 horizon routing 可以把证据权重、refresh trigger �?falsification condition 绑定到正确时间跨度�?

## Failure Mode

- 只新增字段，但实�?memo 仍然混用短期和长期结论�?
- 过度保守，导致真正的 `regime_transition` 被低估�?
- �?horizon bucket 机械套用，忽略研究问题本身的真实时间边界�?

## Evidence Cost

low to medium

短期判断主要依赖财报、指引、consensus 和市场反应；长期判断需要更多产业链、竞争、资本周期和同行证据�?

## Speed Vs Depth

作为 routing step 成本较低；如果进�?`long_term_thesis` �?`regime_transition`，需要更深的证据链�?

## Comparison To Existing Methods

相对现有 `framework-routing`�?

- 现有框架回答“这只票当前由什么变量定价�?
- 本方法先回答“这份结论想解释多长时间�?

相对 `earnings-report-analysis`�?

- 财报 skill 已经能拆短中期经营质�?
- 本方法补上财报结论能否外推到长期 thesis 的门�?

它不是替代现有框架，而是在所有公司研究前面增加一层时间跨度路由�?

## Follow-Through Criteria

- memo 是否更清楚地区分 `earnings impact`、`estimate revision` �?`long-term thesis change`
- `stale_after` �?`must_refresh_if` 是否更具�?
- 财报分析是否减少无证据长期外�?
- 长期 thesis 是否仍保留短期证伪条�?

## Trial Design

- earnings case 1:
  选一只本�?beat 但长期竞争变量未改善的公司，验证方法是否阻止长期外推�?
- earnings case 2:
  选一只本期一般但长期订单、客户或技术路线强化的公司，验证方法是否识�?`regime_transition`�?
- first coverage case:
  选一只产业趋势驱动公司，验证方法是否把长�?thesis 与近期财报兑现分开�?

## Falsification Conditions

- 如果后续 case �?horizon bucket 只是形式字段，不能改变证据权重或刷新条件，应降级�?
- 如果它不能改�?`thesis impact` 的准确性和可证伪性，应退回到普�?framework note�?
- 如果它经常误把短期波动分类为长期拐点，应收紧 `regime_transition` 条件�?

## Adoption Decision

当前判断：`trial`

原因�?

- 内部逻辑缺口明确，且和现�?research loop、framework routing、earnings skill 兼容�?
- 尚缺外部方法论检索和真实案例复盘，不应直接进�?`adopted`�?

## Source Notes

- Internal source: `skills/earnings-report-analysis/SKILL.md`
- Internal source: `skills/equity-research-core/references/framework-routing.md`
- Internal source: `loops/research-loop.md`
- Internal source: `templates/research-package/investment-memo.md`
- User methodology prompt on 2026-05-18
