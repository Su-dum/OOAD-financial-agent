#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LLM 连通性自检。

在做任何调查之前先跑这个，确认：key 有效、模型可访问、JSON 模式可用、延迟可接受。

用法：
  python scripts/check_llm.py
  python scripts/check_llm.py --provider openai          # 临时切到 OpenAI 对照
  python scripts/check_llm.py --prompt "用一句话解释什么是市盈率"

它会读项目根目录的 .env（也可用环境变量）。
"""
import os
import sys
import time
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.app.infrastructure.llm.client import (PRESETS, LLMConfig, LLMError,
                                                  OpenAIChatClient, load_dotenv)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=list(PRESETS), default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-key", default=None,
                    help="临时指定 key（不写进 .env，仅本次生效）")
    ap.add_argument("--base-url", default=None,
                    help="临时指定端点，如中转平台 https://xxx/v1")
    ap.add_argument("--prompt", default="用一句话说明什么是「年化波动率」。")
    ap.add_argument("--json-test", action="store_true", default=True)
    args = ap.parse_args()

    n = load_dotenv(os.path.join(ROOT, ".env"))
    print(f"读取 .env：载入 {n} 个键")

    cfg = LLMConfig.from_env()
    if args.api_key:
        cfg.api_key = args.api_key.strip()
    if args.provider:
        cfg = LLMConfig(provider=args.provider, model=args.model or "",
                        api_key=cfg.api_key,
                        base_url=args.base_url or "")
    elif args.base_url or args.model:
        cfg = LLMConfig(provider=cfg.provider, model=args.model or cfg.model,
                        api_key=cfg.api_key, base_url=args.base_url or cfg.base_url)

    print(f"配置：{cfg.describe()}")
    print(f"API key：{'已配置（' + cfg.api_key[:6] + '...）' if cfg.enabled else '❌ 未配置'}")
    if not cfg.enabled:
        print("\n请在项目根目录创建 .env（可复制 .env.example），填入：")
        print("    LLM_PROVIDER=deepseek")
        print("    LLM_API_KEY=sk-xxxxxxxx")
        return 1

    client = OpenAIChatClient(cfg)

    # ---- 1. 纯文本 ----
    print("\n[1] 纯文本调用")
    try:
        t0 = time.time()
        text = client.complete(args.prompt)
        print(f"    延迟 {time.time()-t0:.1f}s")
        print(f"    返回：{text[:160]}")
    except LLMError as e:
        msg = str(e)
        print(f"    ✗ 失败：{msg}")
        if "401" in msg or "无效" in msg:
            print("\n    【诊断】401 通常意味着 key 与端点不匹配，请核对：")
            print(f"      当前 provider = {cfg.provider}，端点 = {cfg.base_url}")
            print("      · key 是 DeepSeek 的（sk- + 32 位）-> LLM_PROVIDER=deepseek")
            print("      · key 是 OpenAI 的（更长 / sk-proj- 开头）-> LLM_PROVIDER=openai，" \
                  "但国内需代理")
            print("      · key 来自第三方中转平台 -> 设 LLM_BASE_URL 为该平台的 /v1 地址")
        return 2
    except Exception as e:
        msg = str(e)
        print(f"    ✗ 失败：{type(e).__name__}: {msg[:160]}")
        if "Timeout" in msg or "timed out" in msg or "Connect" in msg:
            print("\n    【诊断】连不上端点，多半是网络问题：")
            print(f"      端点 = {cfg.base_url}")
            print("      · OpenAI 在国内需要代理：设 HTTPS_PROXY=http://127.0.0.1:7890 后重试")
            print("      · 或者换成国内可直连的端点（DeepSeek / 中转平台）")
        return 2

    # ---- 2. JSON 模式 ----
    if args.json_test:
        print("\n[2] JSON 模式（结论生成依赖它）")
        prompt = ('请只输出 JSON：{"ok": true, "answer": "一句话", "ids": [1,2]}\n'
                  '问题：A 股每日涨跌幅限制通常是百分比多少？')
        try:
            t0 = time.time()
            data = client.complete_json(prompt, system="你只输出 JSON，不加解释。")
            print(f"    延迟 {time.time()-t0:.1f}s")
            print(f"    解析结果：{json.dumps(data, ensure_ascii=False)[:200]}")
            assert isinstance(data, dict) and "ok" in data
            print("    ✓ JSON 模式可用")
        except Exception as e:
            print(f"    ✗ 失败：{type(e).__name__}: {str(e)[:160]}")

    # ---- 3. 抗幻觉：证据不足时是否承认 ----
    print("\n[3] 抗幻觉检查（证据为空时应承认无法判断）")
    prompt = ("【证据列表】\n（无可用证据）\n\n"
              "【问题】600519 在 2026-07-20 上涨 5.95% 的原因是什么？\n\n"
              '请只输出 JSON：{"conclusion": "...", "confidence": 0~1, '
              '"cited_evidence_ids": [], "insufficient_evidence": true/false}')
    try:
        data = client.complete_json(prompt, system="只能依据给定证据，不得编造。")
        insuff = data.get("insufficient_evidence")
        print(f"    insufficient_evidence = {insuff}")
        print(f"    conclusion = {str(data.get('conclusion'))[:160]}")
        if insuff is True:
            print("    ✓ 模型承认证据不足（符合预期）")
        else:
            print("    ⚠️ 模型没有承认证据不足——实际报告中会被引用校验拦住")
    except Exception as e:
        print(f"    ✗ 失败：{type(e).__name__}: {str(e)[:160]}")

    print("\n自检完成。把 key 写进 .env 后，直接启动 API 即可让调查使用 LLM：")
    print("    python scripts/run_api.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
