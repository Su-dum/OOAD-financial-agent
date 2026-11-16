# LLM 接入说明

> 对应评分项 **B3（事件后自动分析成因）**。
> 结论不再由模板拼接，而是由大模型在**给定证据范围内**归纳，并做引用校验。

## 一、选哪家：DeepSeek 为主，OpenAI 作对照

| 因素 | DeepSeek | OpenAI |
|---|---|---|
| 中文金融文本 | ✅ 训练语料中文占比高 | 中文也不弱，但非主场 |
| 国内直连 | ✅ 无需代理 | ❌ 需代理，稳定性不可控 |
| 成本 | 低一个量级 | 高 |
| 接口兼容 | OpenAI 兼容 | 原生 |

**结论：默认 `deepseek`。** 演示当天网络可达性是最硬的一条约束。

因为两家都是 OpenAI 兼容接口，代码里**只写了一个客户端类**，切换只改配置：

```bash
# .env
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxxxxxxx
```

想临时用 OpenAI 对照：

```bash
python scripts/check_llm.py --provider openai
# 或写进 .env：LLM_PROVIDER=openai
```

预设（`backend/app/infrastructure/llm/client.py::PRESETS`）：

| provider | base_url | 默认 model |
|---|---|---|
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| `custom` | （必须显式设置 `LLM_BASE_URL`） | （必须显式设置 `LLM_MODEL`） |

### 实际接入示例：学校内网网关

本项目实际用的是学校提供的 DeepSeek 网关（**仅校园网可达**）：

```ini
LLM_PROVIDER=custom
LLM_BASE_URL=https://sustech-ooad.dns.navy:19443/v1
LLM_MODEL=deepseek-flash
LLM_FALLBACK_MODEL=deepseek-v4-pro
LLM_API_KEY=sk-xxxx
LLM_MAX_TOKENS=2500
LLM_TIMEOUT=90
```

三个值得记下来的点：

1. **`/v1/models` 列表 ≠ 你可以用的模型。**
   网关返回 14 个模型，但实际调用时报 400 说「只支持 deepseek-flash / deepseek-v4-pro」——
   权限是按 key 配的。被拒时错误信息会告诉你可用列表，照着改即可。
2. **`deepseek-chat` 是公网 API 的名字，自建网关里没有**，要用 `deepseek-v4-pro` 这类。
3. **推理模型的 `max_tokens` 必须给足**（见下一节）。

### ⚠️ 推理模型的坑：`content` 为空

`deepseek-v4-pro` 是**推理模型**，它先输出思考过程（`reasoning_content`），再输出答案
（`content`）。**思考过程的 token 也计入 `completion_tokens`**。

实测把 `max_tokens` 设成 700 时：

```
finish_reason = "length"
completion_tokens = 700   reasoning_tokens = 700    ← 全被思考吃光
content 长度 = 0                                    ← 答案一个字都没有
```

于是结论生成失败、静默降级到模板。**这不是代码 bug，是预算给少了。**

已经做了三层防护：

| 防护 | 行为 |
|---|---|
| 默认 `max_tokens` 提到 **2500** | 一般够用 |
| 检测到 `finish_reason=length` + 空内容 | 自动把预算提到 3 倍重试一次 |
| 仍然为空 | 抛出可读错误「该模型是推理模型，请调大 LLM_MAX_TOKENS」，然后降级到模板 |

'> ### 实测：为什么主力用 flash
>
> 同一批真实事件的单次调查耗时（含证据检索 + LLM 归纳）：
>
> | 模型 | 耗时 | 证据引用 | 抗幻觉 |
> |---|---|---|---|
> | **`deepseek-flash`**（当前主力） | **7.7s / 10.6s** | ✅ 齐全 | ✅ 仍能指出矛盾 |
> | `deepseek-v4-pro`（降级备选） | 34s / 94s | ✅ 齐全 | ✅ 更细致 |
>
> 两者都能正确引用证据、区分相关与因果、承认证据不足；
> `v4-pro` 的结论更细致（会点出"区间收益与事件语义矛盾"这类细节），
> 但慢 4~9 倍，演示时体验差。
>
> **所以主力选 `flash`，`v4-pro` 作为降级备选**（flash 失败时自动切换）。
>
> 一个仍成立的例子：给茅台传一个"跌 6%"的假事件，flash 依然指出
> 「区间累计收益为 +1.84%，现有证据不足以确证成因」——它没有被诱导。'

## 二、配置

1. 复制模板：

```bash
copy .env.example .env      # Windows
cp .env.example .env        # bash
```

2. 填 key：

```ini
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-你的key
# 可选
# LLM_MODEL=deepseek-chat
# LLM_TEMPERATURE=0
# LLM_MAX_TOKENS=700
```

`.env` 已在 `.gitignore` 里（`.gitignore` 第 59 行），**不会提交**。

3. 自检：

```bash
python scripts/check_llm.py
```

它会验证四件事：key 有效、纯文本可调、**JSON 模式可用**、延迟可接受，
并额外跑一次「证据为空时模型是否承认无法判断」的抗幻觉检查。

## 三、防幻觉：三重机制（重点）

提案 4.7「风险二：AI 生成的解释不可靠」写的是「避免把推测性解释表述为已经证实的原因」。
**光在 prompt 里写「不要编造」是没用的**，所以做了结构级约束：

### 1. 证据编号化

喂给模型的证据带编号 `[1]..[n]`，模型只能引用这些编号。

### 2. 强制结构化输出

```json
{
  "conclusion": "3~5 句结论，每句后面标注 [编号]",
  "confidence": 0.0 ~ 1.0,
  "cited_evidence_ids": [1, 3],
  "insufficient_evidence": true | false,
  "hypotheses": ["仍然只是推测的说法"]
}
```

### 3. 引用校验 + 置信度封顶

`LLMConclusionWriter._apply()` 会逐项检查，**任何一项不合格就整段作废、退回模板**：

| 检查 | 不通过时 |
|---|---|
| `conclusion` 非空 | 作废 |
| `cited_evidence_ids` 都是整数 | 作废 |
| **引用的编号真实存在**（1 ≤ id ≤ n） | 作废（判定为幻觉） |
| 有证据时必须至少引用一条 | 作废（判定为无据结论） |
| 置信度不超过证据能支撑的上限 | 截断 |

置信度上限的算法：`min(0.9, 0.3 + 0.12 × 引用条数)`，
若 `insufficient_evidence=true` 再压到 `≤0.5`。
**模型说自己 0.99 分自信，也不会被采信。**

### 4. 事实与推测在类型上就分开

模型返回的 `hypotheses` 只会写进 `report.hypotheses`，
**永远不会进 `report.facts`**。`Evidence`（值对象）只描述「看到了什么」，
不描述「这意味着什么」。

## 四、降级链

```
LLMConclusionWriter（带校验）
   ├─ 正常 → conclusion + llm_meta{cited_evidence_ids, model, degraded:false}
   └─ 任何异常（网络 / 非 JSON / 引用非法 / 结论为空）
          → TemplateConclusionWriter（模板结论，永远可用）
          → llm_meta.degraded = true
```

所以 **API key 没配也能跑**，只是结论是模板拼接的：

```json
{"llm": {"enabled": false, "provider": "deepseek",
         "model": "deepseek-chat", "conclusion_writer": "template"}}
```

报告 markdown 里会明确标注结论来源：

```
> 结论由 deepseek/deepseek-chat 归纳，引用证据 [1, 3]
```

或

```
> 结论由模板生成（LLM 调用降级：llm_fallback）
```

**这一点很关键**：读者永远知道眼前的结论是模型推的还是模板拼的。

## 五、成本

单次调查的用量估算：

| 项 | 量级 |
|---|---|
| 输入 | facts + 最多 15 条证据 ≈ **1.5~2 K tokens** |
| 输出 | 结论 + 推测 ≈ **300 tokens** |
| 单次成本 | 远低于 ¥0.01（具体单价以各官网为准） |

课程项目规模（几十到上百次调查）**总成本在 1 元以内**，不用担心。

## 六、代码位置

| 文件 | 职责 |
|---|---|
| `infrastructure/llm/client.py` | `LLMConfig`、`OpenAIChatClient`（同时支持 DeepSeek/OpenAI）、`.env` 加载 |
| `application/llm_conclusion.py` | `ConclusionWriter` 协议、`TemplateConclusionWriter`、`LLMConclusionWriter`（校验逻辑） |
| `application/investigation_service.py` | `InvestigationAgent` 通过策略注入结论写作者 |
| `api/deps.py` | 读环境变量装配：有 key 就用 LLM，没有就模板 |
| `scripts/check_llm.py` | 连通性与抗幻觉自检 |
| `tests/test_llm.py` | 14 个离线测试（含幻觉引用拦截） |

## 七、测试怎么保证不瞎跑

`tests/test_llm.py` 全部使用**假客户端**，不联网、不花钱，覆盖：

| 用例 | 验证什么 |
|---|---|
| 合法响应被采纳 | 正常路径 |
| 引用 `[9]`（不存在） | **幻觉拦截**，退回模板 |
| `[1][7]` 一半合法 | 仍然整体作废 |
| 有证据但零引用 | 无据结论拦截 |
| 结论为空 | 拦截 |
| 客户端抛异常 | 降级，报告仍可用 |
| 返回非 JSON 文本 | 降级 |
| 客户端只有 `complete()` | 能从文本里抠 JSON，仍可用 |
| 证据 1 条 + 模型说 0.99 | 置信度被截断 |
| `insufficient_evidence=true` | 置信度 ≤ 0.5 |

## 八、已知限制与后续

| 限制 | 说明 |
|---|---|
| 单轮归纳，不是多轮工具调用 | 现在是一次性把证据喂进去。真正的 D2「动态决定还需要什么信息」要改成 ReAct 循环 |
| 未做证据去重排序 | 证据按工具顺序拼，没有按时间/相关度排序 |
| 未做长文摘要 | 公告只取列表标题，`NoticeSearchTool(deep=True)` 才下载 PDF 抽正文 |
| 无缓存 | 同一事件重复调查会重复计费，可按 (code, date, event_type) 缓存 |
| 未评估 prompt 效果 | 建议先跑 `scripts/check_llm.py`，再用真实事件调整 `_SYSTEM_PROMPT` |
