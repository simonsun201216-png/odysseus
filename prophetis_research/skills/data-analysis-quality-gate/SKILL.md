# Data Analysis Quality Gate

这个 skill 用于�?Prophetis 研究中判断数量型结论是否需要可复算数据、工具计算或显式降级�?

它不是一个独立数据分析插件，也不绑定 Data Analytics、Python、Spreadsheet 或外�?API。它的职责是�?LLM 从“直接给数字结论”约束为�?

- 先提出数据需�?
- 再判断是否必须计�?
- 决定是否需要征求用户同意动用工�?
- 记录公式、口径、来源和限制
- 对没有完成计算的数量型结论降�?

## Use When

当研究结论涉及以下任一内容时，必须进入�?gate，或明确写明 waived reason�?

- 同比、环比、CAGR、run-rate、margin bridge
- peer comparison、peer ranking、相对估值、相对财务质�?
- valuation implied expectation、base / bull / bear scenario math
- 市场规模、渗透率、份额、TAM / SAM / SOM
- 三表交叉校验、现金流质量、营运资本异�?
- 宏观、商品、价格、库存、利率、就业或通胀时间序列
- 多来源数字冲突或口径不一�?
- 任何会影�?`thesis_impact`、`research_action`、`actionability_bridge` �?durable conclusion 的数量判�?

## Inputs

- `research_object`
- `research_question`
- `market_scope`
- `time_boundary`
- `candidate_numeric_claims`
- `available_sources`
- `user_speed_preference`
  可选。若用户明确要求快看，可降低计算深度，但不能升级结论强度�?
- `tool_constraints`
  可选。说明是否允许本地脚本、CSV、Spreadsheet、联网、外�?API 或插件�?

## Gate Output

每次运行�?gate，至少输出：

- `quant_dependency`
  `none` / `low` / `medium` / `high`
- `calculation_required`
  `yes` / `no`
- `data_requirement_brief_required`
  `yes` / `no`
- `calculation_ledger_required`
  `yes` / `no`
- `tool_consent_required`
  `yes` / `no`
- `allowed_without_tool`
  `yes` / `no`
- `downgrade_if_not_calculated`
  `none` / `calculation_gap` / `source_gap` / `watch_only` / `needs_refresh`
- `recommended_tool_path`
  `none` / `manual_formula_note` / `local_csv_script` / `spreadsheet` / `python` / `public_api` / `external_plugin`
- `calculation_depth`
  `none` / `formula_note` / `ledger_required` / `full_model_required`
- `refresh_condition`

## Calculation Depth

### `none`

用于没有派生数量结论，或数量只作为非核心背景且已有可靠来源直接披露的场景�?

输出要求�?

- 记录 `quant_dependency: none` �?`low`
- 不生�?calculation artifact

### `formula_note`

用于简单、低行数、可口头复核的计算，例如一个同比、一�?run-rate sanity check、简单估值倍数或明确公式的市场隐含值�?

输出要求�?

- 在正文或 source note 写明公式、输入来源、期间和限制
- evidence log 可记�?`claim_type=derived_calculation`
- 不默认生�?`calculation-ledger.csv`

### `ledger_required`

用于会影�?thesis impact、research action、actionability bridge、peer ranking、scenario table 或多来源冲突处理的计算�?

输出要求�?

- 使用 `templates/calculation-ledger.csv`
- 记录输入来源、公式、结果、交叉校验、限制和对应 evidence ref
- 若缺失数据阻断结论，输出 `data-requirement-brief.md` �?`source_gap`

### `full_model_required`

用于多变量估值、三表联动、复�?peer set、时间序列、宏�?商品历史比较、TAM / SAM / SOM 或需要用户复用的 spreadsheet / script�?

输出要求�?

- 先明确工具和数据权限
- 生成可复�?model、script、spreadsheet �?notebook，并把摘要写�?calculation ledger
- 如果用户选择不做，相关结论只能是 `watch_only`、`needs_refresh`、`source_gap` �?`calculation_gap`

## Data Requirement Brief

如果 `data_requirement_brief_required = yes`，或 `calculation_depth` �?`ledger_required` / `full_model_required` 且关键输入缺失，使用�?

- `templates/data-requirement-brief.md`

brief 必须回答�?

- 要回答的研究问题
- 需要哪些变�?
- 指标公式或计算方�?
- 口径、单位、币种和期间
- 对比对象�?peer set
- 来源优先�?
- 缺失数据如何处理
- 哪些缺失会导致结论降�?

## Calculation Ledger

如果 `calculation_ledger_required = yes`，或 `calculation_depth` �?`ledger_required` / `full_model_required`，使用：

- `templates/calculation-ledger.csv`

ledger 必须记录�?

- 计算 ID
- 研究对象和问�?
- 指标、公式、期间、单�?
- 输入来源
- 结果
- 交叉校验
- 使用工具
- 验证状�?
- 限制
- 对应 evidence log ref

## Tool Consent Rules

默认不因为本 gate 自动引入插件或联网�?

可以直接使用工具的场景：

- 用户已经提供 CSV、表格或可读数据
- 只需要小规模本地计算
- 不需要联网、下载数据、外�?API 或额外插�?
- 输出可用 formula note �?calculation ledger 复核

必须先征求用户意见的场景�?

- 需要联网抓取或下载数据
- 需要使用外�?API、付费数据源或登录�?
- 需要引入插件或新依�?
- 需要生成较大的 spreadsheet、dashboard 或图表包
- 计算会明显改变任务范围或耗时

建议话术�?

> 这个判断依赖可复算计算。仅靠文本阅读容易出错。建议进�?calculation gate，用本地 CSV/Python/Spreadsheet 生成 calculation ledger；是否继续？

## Downgrade Rules

如果数量型结论没有完成必要计算：

- 不得写成 durable conclusion�?
- 不得作为 `research_action` �?`actionability_bridge` 的唯一依据�?
- 必须标记 `calculation_gap` �?`source_gap`�?
- 如果用户要求快看，可�?`calculation_waived_by_speed`，但置信度不得高�?`low` �?`medium`�?
- 如果估值锚、共识代理或 peer rank 缺失，actionability 默认降级�?`watch_only`、`needs_refresh` �?`no_action`�?

## Evidence Log Relationship

`evidence-log.csv` 记录 claim 来源和性质�?

`calculation-ledger.csv` 记录公式、口径和复算路径�?

派生计算结论必须同时满足�?

- evidence log 中有 `claim_type=derived_calculation` �?explicit source note
- `upstream_sources` 指向 L1-L5 来源
- calculation ledger �?formula note 记录可复算步�?

## Output Boundaries

- 不要�?market pricing 写成基本面验证�?
- 不要�?company guidance 写成已兑现事实�?
- 不要�?LLM 心算结果写成高置信结论�?
- 不要因为工具输出了数字就自动提高投资结论强度�?
- 工具只提高计算可复核性，不替代来源质量和 thesis judgment�?
