# Variant Perception Checklist

- company_name: {{ company_name }}
- ticker: {{ ticker }}
- research_cutoff_date: {{ research_cutoff_date }}
- selected_framework: {{ selected_framework }}
- status: {{ status }}
- not_investment_advice: true

## 1. Consensus Proxy

至少写出 `2` �?`3` 个共识代理，不允许只写一句“市场预期如何”�?

- `sell_side_proxy`
  例如一致评级、目标价区间、常见模型假�?
- `price_action_proxy`
  例如财报后反应、阶段涨跌、估值位置、拥挤价格行�?
- `narrative_proxy`
  例如市场主流 bull / bear 叙事、媒体和研究反复强调的焦�?

{{ consensus_proxy }}

## 2. What Is Mispriced

市场最可能错价的具体变量是什么？

不要写成抽象判断，优先落到变量层�?

- 收入增�?
- 毛利�?
- 需求斜�?
- 库存
- capex
- 定价�?
- 监管影响
- 竞争格局
- 估值锚

{{ what_is_mispriced }}

## 3. Why Market May Be Wrong

市场为什么会错？

常见原因�?

- 锚定旧叙�?
- 把短期噪音外推过�?
- 把单一业务线当成全�?
- 忽略供给、需求或竞争结构变化
- 忽略宏观与行�?regime 已切�?

{{ why_market_may_be_wrong }}

## 4. What Changes The Price

如果你的分歧判断是对的，价格通过什么路径重估？

至少写清�?

- `catalyst`
- `time_window`
- `transmission_path`

{{ what_changes_the_price }}

## 5. What Falsifies The View

什么条件出现，说明这个分歧判断失效�?

优先写可以观察和跟踪的条件：

- 下一次财�?指引
- 渠道与库存数�?
- 监管进展
- 订单或客户行�?
- 估值和价格反应背离

{{ what_falsifies_the_view }}

## Provisional Judgment

最后只允许落到以下三种之一�?

- `wide variant`
  预期差明显，且共识可识别
- `thin variant`
  分歧存在，但 edge 不够�?
- `no usable variant`
  很难刻画共识，或价格已充分反�?

{{ provisional_judgment }}
