# -*- coding: utf-8 -*-
"""LLM 适配器：OpenAI 兼容客户端。

DeepSeek 与 OpenAI 都提供 OpenAI 兼容的 `/chat/completions` 接口，
所以**一个类就能同时支持两家**，切换只改配置（provider / base_url / model）。

不额外依赖 openai SDK，直接用 requests —— 少一个依赖，行为也更可预测。
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests

# ---------------------------------------------------------------- 预设
# 价格为量级参考，实际以各官网为准；本项目调用量极小，成本可忽略。
PRESETS: dict[str, dict] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "note": "官方公网端点，中文强、国内直连、成本低。",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "note": "官方端点，国内需代理；适合做对照实验。",
    },
    "custom": {
        "base_url": "",
        "model": "",
        "note": "任意 OpenAI 兼容端点（学校内网网关 / 第三方中转）。"
                "必须显式设置 LLM_BASE_URL 与 LLM_MODEL。",
    },
}


def load_dotenv(path: str | Path) -> int:
    """极简 .env 读取（不引入 python-dotenv）。

    已存在的环境变量不会被覆盖。返回载入的键数。
    """
    p = Path(path)
    if not p.exists():
        return 0
    n = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in __import__("os").environ:
            __import__("os").environ[k] = v
            n += 1
    return n


@dataclass
class LLMConfig:
    provider: str = "deepseek"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.0
    # 推理模型（deepseek-v4-pro / r1 等）的思考过程也计入 completion_tokens，
    # 预算给小了会出现 finish_reason=length 且 content 为空，所以默认给足。
    max_tokens: int = 2500
    timeout: int = 90
    max_retries: int = 3
    # 主模型连续失败后自动降级的备用模型（如网关 502 / 上游超时）。
    # 设成更轻的模型通常更容易成功，保证演示不中断。
    fallback_model: str = ""

    def __post_init__(self):
        preset = PRESETS.get(self.provider, PRESETS["deepseek"])
        self.model = self.model or preset["model"]
        self.base_url = (self.base_url or preset["base_url"]).rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls, env=None) -> "LLMConfig":
        import os
        env = env or os.environ
        provider = (env.get("LLM_PROVIDER") or "deepseek").strip().lower()
        if provider not in PRESETS:
            provider = "deepseek"
        return cls(
            provider=provider,
            model=(env.get("LLM_MODEL") or "").strip(),
            api_key=(env.get("LLM_API_KEY") or "").strip(),
            base_url=(env.get("LLM_BASE_URL") or "").strip(),
            temperature=float(env.get("LLM_TEMPERATURE") or 0.0),
            max_tokens=int(env.get("LLM_MAX_TOKENS") or 2500),
            timeout=int(env.get("LLM_TIMEOUT") or 90),
            fallback_model=(env.get("LLM_FALLBACK_MODEL") or "").strip(),
        )

    def describe(self) -> str:
        return (f"{self.provider}/{self.model} @ {self.base_url} "
                f"(temp={self.temperature}, max_tokens={self.max_tokens})")


class LLMError(RuntimeError):
    pass


class _Transient(LLMError):
    """可重试的错误（429 限流、5xx 上游故障）。"""


class OpenAIChatClient:
    """满足 application 层的 LLMClient 协议（`complete(prompt) -> str`）。"""

    def __init__(self, config: LLMConfig, log=print):
        self.config = config
        self.log = log
        self.last_usage: Optional[dict] = None
        self.last_model: str = ""
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        })

    # ---------------- 底层 ----------------
    def _chat(self, messages: list[dict], temperature: Optional[float] = None,
              max_tokens: Optional[int] = None,
              response_format: Optional[dict] = None) -> str:
        """按「主模型 -> 备用模型」依次尝试，每个模型内部再做退避重试。"""
        if not self.config.enabled:
            raise LLMError("未配置 API key（设置环境变量 LLM_API_KEY 或写入 .env）")
        if not self.config.base_url:
            raise LLMError("未配置端点（设置 LLM_BASE_URL，例如 https://xxx/v1）")

        models = [self.config.model]
        fb = getattr(self.config, "fallback_model", "")
        if fb and fb != self.config.model:
            models.append(fb)

        last_err: Optional[Exception] = None
        for mi, model in enumerate(models):
            try:
                return self._chat_once(model, messages, temperature, max_tokens,
                                       response_format)
            except LLMError as e:
                last_err = e
                if mi + 1 < len(models):
                    if self.log:
                        self.log(f"  [llm] {model} 失败（{str(e)[:70]}），"
                                 f"降级到备用模型 {models[mi+1]}")
                    continue
                raise
        raise last_err or LLMError("调用失败")

    def _chat_once(self, model: str, messages: list[dict],
                   temperature: Optional[float], max_tokens: Optional[int],
                   response_format: Optional[dict]) -> str:
        budget = self.config.max_tokens if max_tokens is None else max_tokens
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": budget,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format

        url = f"{self.config.base_url}/chat/completions"
        last_err: Optional[Exception] = None
        bumped = False

        for attempt in range(self.config.max_retries + 1):
            try:
                t0 = time.time()
                r = self._session.post(url, json=payload, timeout=self.config.timeout)

                if r.status_code == 401:
                    raise LLMError("API key 无效或已过期（401）")
                if r.status_code == 429:
                    raise _Transient(f"限流（429）：{r.text[:120]}")
                if r.status_code >= 500:
                    # 网关上游故障（实测有 502 Failed to read upstream response），可重试
                    raise _Transient(f"HTTP {r.status_code}：{r.text[:150]}")
                if r.status_code >= 400:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")

                js = r.json()
                ch = (js.get("choices") or [{}])[0]
                msg = ch.get("message") or {}
                content = (msg.get("content") or "").strip()
                finish = ch.get("finish_reason")
                self.last_usage = js.get("usage")
                self.last_model = model
                if self.log:
                    u = self.last_usage or {}
                    self.log(f"  [llm] {model} {time.time()-t0:.1f}s finish={finish} "
                             f"tokens in={u.get('prompt_tokens')} "
                             f"out={u.get('completion_tokens')}")

                if content:
                    return content

                # ---- 空内容：多半是推理模型把预算吃光了 ----
                reasoning = msg.get("reasoning_content") or ""
                if finish == "length" and not bumped and max_tokens is None:
                    bumped = True
                    payload["max_tokens"] = budget * 3
                    if self.log:
                        self.log(f"  [llm] finish_reason=length（reasoning "
                                 f"{len(reasoning)} 字符），把 max_tokens 提到 "
                                 f"{payload['max_tokens']} 重试")
                    continue
                raise LLMError(
                    f"模型未产出内容（finish_reason={finish}，reasoning 长度 {len(reasoning)}）。"
                    f"该模型是推理模型，请调大 LLM_MAX_TOKENS（当前 {payload['max_tokens']}）")

            except _Transient as e:
                last_err = e
                wait = 2 * (attempt + 1)
                if self.log:
                    self.log(f"  [llm] 瞬时错误（{str(e)[:60]}）第 {attempt+1} 次，"
                             f"退避 {wait}s")
                if attempt < self.config.max_retries:
                    time.sleep(wait)
            except LLMError:
                raise
            except Exception as e:
                last_err = e
                wait = 2 * (attempt + 1)
                if self.log:
                    self.log(f"  [llm] 第 {attempt+1} 次失败: {type(e).__name__} -> {wait}s")
                if attempt < self.config.max_retries:
                    time.sleep(wait)
        raise LLMError(f"调用失败: {type(last_err).__name__}: {last_err}")

    # ---------------- 对外 ----------------
    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        return self._chat(msgs)

    def complete_json(self, prompt: str, system: Optional[str] = None) -> dict:
        """要求模型返回 JSON。

        先试 `response_format=json_object`；若网关不支持（HTTP 400 / 参数非法），
        自动退化为「纯文本 + 自己抠 JSON」，保证换端点后不用改代码。
        """
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        try:
            text = self._chat(msgs, response_format={"type": "json_object"})
        except LLMError as e:
            msg = str(e).lower()
            unsupported = ("400" in msg or "unsupported" in msg or "invalid" in msg
                           or "response_format" in msg or "json_object" in msg)
            if not unsupported:
                raise
            if self.log:
                self.log(f"  [llm] 该端点不支持 json_object 模式，退化为文本解析")
            text = self._chat(msgs)

        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            lo, hi = text.find("{"), text.rfind("}")
            if lo >= 0 and hi > lo:
                try:
                    return json.loads(text[lo:hi + 1])
                except json.JSONDecodeError:
                    pass
        raise LLMError(f"模型返回的不是合法 JSON：{text[:200]}")
