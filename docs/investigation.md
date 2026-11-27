# 事件调查（B3 + D2）

> 对应评分项 **B3（检测到事件后自主检索并分析成因）** 与 **D2（多步调查）**。
> D2 原文：*autonomously decompose the investigation into multiple subtasks and
> dynamically determine what additional information or analysis is needed.*

## 一、D2 到底要什么

两个动词，缺一不可：

| 动词 | 含义 | 判断依据 |
|---|---|---|
| **decompose into subtasks** | 把调查拆成若干**有明确问题**的子任务 | 报告里每一步写的是「要回答什么问题」，不是「调用哪个工具」 |
| **dynamically determine** | 下一步由上一步的结果决定 | 换一种事件，路径会不会变 |

⚠️ 只做到第一个就是**批处理冒充调查**：把 3 个工具写死顺序各跑一次也"有 3 步"，
但没有反馈环。本项目改造前就是这种状态——三种不同类型的事件跑出**完全相同**的
`[news_search, notice_search, indicator_analysis]`。

## 二、结构

```
InvestigationAgent（编排）
  ├─ InvestigationPlanner（决策：下一步查什么 / 何时停）
  │    ├─ LLMPlanner         模型从动作菜单里选 + 给理由
  │    └─ HeuristicPlanner   「缺什么补什么」的确定性规则（无 LLM 时的兜底）
  └─ InvestigationTool（执行：只产出 Evidence，不产出结论）
       ├─ NewsSearchTool      news_search / news_widen
       ├─ NoticeSearchTool    notice_search / notice_deep
       ├─ IndicatorTool       indicator
       └─ IndustryCompareTool industry
```

主循环（`investigation_service.py`）：

```
while 步数 < 预算:
    看当前证据 -> 规划器选下一步 -> 执行工具 -> 证据并入 -> 回到开头
规划器说 stop / 步数用完 / 没有可执行动作 -> 结束
然后 事实 -> 推测 -> 结论（模板或 LLM + 引用校验）
```

## 三、动作菜单

| 动作 | 中文 | 什么时候会被选 |
|---|---|---|
| `indicator` | 区间指标 | 建立价格事实基准（涨跌幅/波动/回撤） |
| `notice_search` | 检索公告 | 查公司披露（财报/分红/回购/增减持/监管） |
| `notice_deep` | 公告正文 | 只有标题不够时，下**巨潮 PDF** 抽正文（每次最多 2 份，控时长） |
| `news_search` | 个股新闻 | 按公司名检索消息面 |
| `news_widen` | 扩窗检索 | **个股新闻一条都没有时**：换行业关键词 + 放宽 30 天重试 |
| `industry` | 行业联动 | 公司层面证据不足时，查申万行业指数同期表现，区分「行业性回调」vs「个股特有」 |
| `stop` | 结束 | 证据已足够回答成因与影响 |

动作与工具的对应由工具的 `actions` 属性声明，一个工具可服务多个动作
（`NewsSearchTool.actions = ("news_search", "news_widen")`）。

## 四、实测：路径确实随事件变化

4 个不同类型的事件（真实数据 + 真实 LLM 规划）：

| 事件 | 走出的路径 | 步数 |
|---|---|---|
| 价格异动（宁德时代 -8.33%） | `indicator > news_search > notice_search > industry` | 4 |
| 财报披露（茅台三季报） | `notice_search > news_search > indicator > industry` | 4 |
| 统计异常（紫金矿业 z=3.6） | `news_search > news_widen > industry > notice_search > indicator` | 5 |
| 统计异常（平安银行 z=5.6） | `indicator > news_search > news_widen > industry > notice_search` | 5 |

- **不同路径 4/4**，步数 4~5 不等（改造前恒为 3 且顺序固定）
- 「个股新闻 0 条 → 追加 `news_widen`」在 2 个事件里真实发生
- 每一步都带 LLM 给的**理由**，例如：

  > 第 3 步 `industry`：个股跌幅（-13.52%）明显大于电力设备行业（-9.19%），
  > 存在约 4.3 个百分点的个股特异性下跌，需判断是否由锂电板块整体回落驱动。

## 五、兜底：LLM 不可靠也不能让调查崩

| 风险 | 处理 |
|---|---|
| LLM 调用失败（网关 5xx） | 退回 `HeuristicPlanner`，一步照走 |
| 模型选了菜单外的动作 | 退回规则决策 |
| 模型重复选已执行的动作 | 退回规则决策；规则也说不出下一步 → `stop` |
| 死循环 | 每个动作**最多执行一次** + `max_steps` 上限（默认 5） |
| 结论不合格 | `LLMConclusionWriter` 的引用校验（编造编号 → 整段退回模板） |
| 证据重复 | 按 `(kind, title)` 去重（新闻两轮检索、公告检索与下正文都可能命中同一条） |

## 六、性能取舍

- **手动调查**（用户点「调查」）：`LLMPlanner` + 允许下 PDF。慢一些（约 30~60s），但换来
  真正的模型决策与更实的证据。
- **自动调查**（刷新/巡检时）：`HeuristicPlanner` + 不下 PDF，结论仍由 LLM 归纳。
  这样刷新时长可控（实测 light 档 0.1~8s），且路径**依然随证据变化**。
- `INVESTIGATE_MAX_STEPS` 环境变量可调预算。

## 七、前端呈现

报告面板（`ReportView.tsx`）把"动态"直接摆出来：

- 头部徽标 **`LLM 逐步决策`** / `规则逐步决策`
- 「调查步骤（N）」：每一步显示 `第 k 步 · 要回答的问题 ·（动作名，命中数）`
- 每步下面一行 **「为什么走这步：…」**——这是规划决策的原文
- 列表末尾 **「结束原因：…」**（信息足够 / 达到步数上限）

## 八、已知限制

| 限制 | 影响 | 后续 |
|---|---|---|
| `notice_deep` 依赖巨潮能取到同一份公告 | 取不到时这一步只拿到标题（无正文） | 可加「按标题匹配巨潮列表」的补全 |
| 没有 `peer_compare`（同行对比）动作 | 只能确认行业联动，不能定位到具体同行 | 加一个同行业 2~3 只票的对比工具 |
| 步数与路径依赖模型稳定性 | 同一事件两次调查路径可能不同 | 属正常现象；`stop_reason` 会说明依据 |
| `LLMPlanner` 每步一次模型调用 | 手动调查比固定流水线慢 3~5 倍 | 已用规则规划器承载自动调查 |
