# -*- coding: utf-8 -*-
"""控制台编码小工具。

Windows 中文控制台默认是 GBK（cp936），直接 `print("✓")` 会抛：

    UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'

脚本里的检查标记（✓ / ✗ / ⚠️）都会踩到这个坑，而这只在「真实的 Windows 终端」
里发生，在管道/日志重定向时反而正常——典型的「本机能跑、别人一跑就崩」。

所以统一在脚本入口调用 `enable_utf8()`：把 stdout/stderr 换成 UTF-8 + replace，
编码不支持时最多显示成占位符，不会中断整个验收流程。
"""
import sys


def enable_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                              # noqa: BLE001
            pass
