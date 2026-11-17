# -*- coding: utf-8 -*-
"""akshare 版本兼容层的测试（不需要真的装 akshare）。

背景：akshare 1.20.44 起批量重命名接口（`stock_zh_a_hist` -> `stock_zh_a_hist_em`），
而 requirements 只锁下限。没有兼容层的话，演示机装到新版就 AttributeError，
而这种问题**离线单测完全看不出来**。所以这里用桩模块验证解析逻辑。
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.infrastructure.providers import akshare_compat as compat


@pytest.fixture(autouse=True)
def clear_cache():
    compat._resolved.clear()
    yield
    compat._resolved.clear()


@pytest.fixture()
def fake_ak(monkeypatch):
    """造一个「新版」akshare：只有改名后的接口。"""

    mod = types.SimpleNamespace(
        __version__="1.20.65",
        stock_zh_a_hist_em=lambda **kw: ("em", kw),
        stock_zh_a_hist_sina=lambda **kw: ("sina", kw),
        index_zh_daily_sina=lambda **kw: ("index", kw),
        stock_news_global_em=lambda **kw: ("news_em", kw),
        stock_news_global_cls=lambda **kw: ("news_cls", kw),
    )
    monkeypatch.setitem(sys.modules, "akshare", mod)
    return mod


@pytest.fixture()
def old_ak(monkeypatch):
    """造一个「旧版」akshare：只有改名前的接口。"""
    mod = types.SimpleNamespace(
        __version__="1.12.0",
        stock_zh_a_hist=lambda **kw: ("old_hist", kw),
        stock_zh_a_daily=lambda **kw: ("old_daily", kw),
        stock_zh_index_daily=lambda **kw: ("old_index", kw),
    )
    monkeypatch.setitem(sys.modules, "akshare", mod)
    return mod


def test_new_names_are_resolved(fake_ak):
    assert compat.call("stock_zh_a_hist", symbol="600519")[0] == "em"
    assert compat.call("stock_zh_a_daily", symbol="sh600519")[0] == "sina"
    assert compat.call("stock_zh_index_daily", symbol="sh000300")[0] == "index"
    assert compat.call("stock_info_global_em")[0] == "news_em"
    assert compat.call("stock_info_global_cls", symbol="全部")[0] == "news_cls"


def test_old_names_still_work(old_ak):
    assert compat.call("stock_zh_a_hist", symbol="600519")[0] == "old_hist"
    assert compat.call("stock_zh_a_daily")[0] == "old_daily"
    assert compat.available("stock_zh_index_daily") is True


def test_unknown_name_raises(fake_ak):
    with pytest.raises(AttributeError) as exc:
        compat.call("stock_not_a_real_function")
    assert "尝试过" in str(exc.value)


def test_available_false_for_missing(fake_ak):
    assert compat.available("stock_info_global_em") is True
    assert compat.available("nothing_here") is False


def test_resolution_is_cached(fake_ak):
    compat.call("stock_zh_a_hist")
    name, fn = compat.resolve("stock_zh_a_hist")
    assert name == "stock_zh_a_hist_em"
    assert compat.resolve("stock_zh_a_hist")[0] == name    # 命中缓存，不再解析
