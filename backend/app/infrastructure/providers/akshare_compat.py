# -*- coding: utf-8 -*-
"""akshare 版本兼容层。

## 为什么需要这一层

`requirements.txt` 只写了 `akshare>=1.20`（锁下限、不锁上限），而 akshare
在 **1.20.44 起批量重命名了接口**：

| 旧名（本项目最初验证时） | 新名（1.20.44+） |
|---|---|
| `stock_zh_a_hist` | `stock_zh_a_hist_em` |
| `stock_zh_a_daily` | `stock_zh_a_hist_sina` |
| `stock_zh_index_daily` | `index_zh_daily_sina` |
| `stock_info_global_em` | `stock_news_global_em` |
| `stock_info_global_cls` | `stock_news_global_cls` |

旧名会抛 `AttributeError: ... 已更名为 ...`。演示机重装依赖后如果装到新版，
整条取数链路就全挂——而这类问题**单测看不出来**（测试全部离线）。

所以把「名字」这一层不确定性收敛到一个文件：调用方永远用**旧名**（语义稳定），
这里负责解析到当前版本真实存在的函数。

## 为什么不直接写新名

课程环境的依赖可以重装成任意版本；保留旧名 + 候选解析，
新旧两种环境都能跑，且升级 akshare 不需要改业务代码。
"""
from typing import Any, Callable, Tuple

# 旧名 -> 当前版本可能的正式名（按优先级）
_RENAMES: dict = {
    "stock_zh_a_hist": ("stock_zh_a_hist_em",),
    "stock_zh_a_daily": ("stock_zh_a_hist_sina",),
    "stock_zh_index_daily": ("index_zh_daily_sina",),
    "stock_zh_index_daily_tx": ("index_zh_daily_tx",),
    "stock_info_global_em": ("stock_news_global_em",),
    "stock_info_global_cls": ("stock_news_global_cls",),
}

_resolved: dict = {}


def resolve(name: str) -> Tuple[str, Callable]:
    """返回 (当前版本的真实函数名, 函数对象)。找不到抛 AttributeError。"""
    if name in _resolved:
        return _resolved[name]
    import akshare as ak
    for cand in (name,) + _RENAMES.get(name, ()):
        fn = getattr(ak, cand, None)
        if callable(fn):
            _resolved[name] = (cand, fn)
            return _resolved[name]
    tried = ", ".join((name,) + _RENAMES.get(name, ()))
    raise AttributeError(f"当前 akshare({getattr(ak, '__version__', '?')}) 没有可用接口："
                         f"尝试过 {tried}。请检查 akshare 版本或更新兼容表。")


def call(name: str, *args, **kwargs) -> Any:
    """按旧名调用（自动解析到当前版本的正式名）。"""
    _, fn = resolve(name)
    return fn(*args, **kwargs)


def available(name: str) -> bool:
    try:
        resolve(name)
        return True
    except AttributeError:
        return False


def version() -> str:
    try:
        import akshare as ak
        return str(getattr(ak, "__version__", "?"))
    except Exception:                                   # noqa: BLE001
        return "not-installed"
