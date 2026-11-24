# -*- coding: utf-8 -*-
"""分析任务（C1）的测试：校验、持久化、一键重跑。"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db as dbmod
from backend.app.application.task_service import (AnalysisTaskService,
                                                  TaskValidationError)
from backend.app.domain.events import MarketEvent
from backend.app.domain.models import IndicatorSet, PriceRecord, PriceSeries
from backend.app.infrastructure.repositories.analysis_task_repository import (
    SqliteAnalysisTaskRepository)


class StubCatalog:
    def name_of(self, code):
        return {"600519": "贵州茅台", "000001": "平安银行"}.get(code, "")

    def industry_of(self, code):
        return "食品饮料"


class StubAnalyzer:
    def __init__(self):
        self.calls = []

    def analyze(self, code, start, end, **kw):
        self.calls.append((code, start, end))
        dates = ["2026-05-01", "2026-05-02", "2026-05-03"]
        closes = [100.0, 101.0, 102.0]
        return IndicatorSet(
            code=code, name="贵州茅台", industry_l1="食品饮料",
            start=dates[0], end=dates[-1], n_days=len(dates),
            total_return=0.02, annualized_volatility=0.2,
            max_drawdown=-0.05, sharpe=0.5)


class StubMonitor:
    def scan(self, code, start, end, **kw):
        return [MarketEvent(code=code, name="贵州茅台", event_type="price_surge",
                            trade_date=end, detected_at="now", severity="medium",
                            value=0.06, threshold=0.05, detail="涨 6%",
                            rule_name="threshold")]


class StubCross:
    def compare(self, codes, start, end, benchmark=None, **kw):
        return dict(n_days=242, assets=[dict(code=c, total_return=0.1)
                                        for c in codes],
                    correlation=dict(codes=list(codes), matrix=[[1.0]]),
                    benchmark=dict(symbol=benchmark or "sh000300"),
                    note="")


@pytest.fixture()
def con(tmp_path):
    c = dbmod.connect(tmp_path / "t.db")
    dbmod.init_schema(c)
    yield c
    try:
        c.close()
    except Exception:
        pass


@pytest.fixture()
def svc(con):
    return AnalysisTaskService(SqliteAnalysisTaskRepository(con, log=None),
                               StubAnalyzer(), monitor=StubMonitor(),
                               cross=StubCross(), catalog=StubCatalog(), log=None)


# ============================================================
# 1. 校验
# ============================================================
@pytest.mark.parametrize("name,code,days,codes,msg", [
    ("", "600519", 365, [], "任务名"),
    ("  ", "600519", 365, [], "任务名"),
    ("x" * 41, "600519", 365, [], "太长"),
    ("日常", "abc", 365, [], "代码"),
    ("日常", "600519", 3, [], "天数"),
    ("日常", "600519", 5000, [], "天数"),
    ("日常", "999999", 365, [], "映射表"),
    ("日常", "600519", 365, ["000001", "000002", "000003", "000004", "000005",
                             "000006"], "最多"),
])
def test_create_validation(svc, name, code, days, codes, msg):
    with pytest.raises(TaskValidationError, match=msg):
        svc.create(name, code, days, codes)


def test_create_dedupes_and_drops_self(svc):
    task = svc.create("日常", "600519", 180, ["600519", "000001", "000001"])
    assert task.code == "600519"
    assert task.compare_codes == ("000001",)
    assert task.days == 180


# ============================================================
# 2. 持久化
# ============================================================
def test_repository_roundtrip(con):
    repo = SqliteAnalysisTaskRepository(con, log=None)
    tid = repo.create(_task())
    assert tid > 0
    got = repo.get(tid)
    assert got.name == "茅台月度" and got.compare_codes == ("000001",)
    assert repo.list()[0].id == tid
    repo.touch(tid)
    assert repo.get(tid).last_run_at
    assert repo.count() == 1
    assert repo.delete(tid) is True
    assert repo.count() == 0
    assert repo.delete(tid) is False


def _task():
    from backend.app.domain.analysis_task import AnalysisTask
    return AnalysisTask(name="茅台月度", code="600519", days=30,
                        compare_codes=("000001",), benchmark="sh000300",
                        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def test_service_list_and_delete(svc):
    t1 = svc.create("任务一", "600519", 365)
    t2 = svc.create("任务二", "000001", 180)
    items = svc.list()
    assert [i["name"] for i in items] == ["任务二", "任务一"]   # 新的在前
    assert svc.delete(t1.id) is True
    assert len(svc.list()) == 1


# ============================================================
# 3. 一键重跑
# ============================================================
def test_run_returns_bundle(svc):
    task = svc.create("日常", "600519", 365, ["000001"])
    body = svc.run(task.id)
    assert body["task"]["code"] == "600519"
    assert body["indicator"]["total_return"] == pytest.approx(0.02)
    assert body["event_count"] == 1
    assert body["events"][0]["event_type"] == "price_surge"
    assert len(body["periods"]) >= 1
    assert all("total_return" in p for p in body["periods"])
    # 有对比标的 -> 附带跨资产结果
    assert body["cross"]["n_days"] == 242
    assert body["cross"]["benchmark"]["symbol"] == "sh000300"


def test_run_without_compare_codes_skips_cross(con):
    svc = AnalysisTaskService(SqliteAnalysisTaskRepository(con, log=None),
                              StubAnalyzer(), monitor=StubMonitor(),
                              cross=StubCross(), catalog=StubCatalog(), log=None)
    task = svc.create("单票", "600519", 90)
    body = svc.run(task.id)
    assert body["cross"] is None


def test_run_records_last_run_time(svc):
    task = svc.create("日常", "600519", 90)
    svc.run(task.id)
    assert svc.list()[0]["last_run_at"]


def test_run_missing_task_raises(svc):
    with pytest.raises(TaskValidationError, match="不存在"):
        svc.run(999)


def test_period_windows_respect_task_length():
    from backend.app.domain.analysis_task import period_windows
    assert [d for _, d in period_windows(30)] == [30]
    assert [d for _, d in period_windows(365)] == [30, 90, 180, 365]
    assert [d for _, d in period_windows(730)] == [30, 90, 180, 365, 730]
