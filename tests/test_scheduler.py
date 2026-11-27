# -*- coding: utf-8 -*-
"""定时巡检排班的单元测试（完全离线：用假 RefreshService，不碰任何数据源）。

重点是 `should_run(now)` —— 它是**纯判断**，可以传任意时间点，
所以「盘中每 30 分钟 / 盘后两个固定时点 / 只工作日」这些规则都能被锁死，
不用真的等到 16:00。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db as dbmod
from backend.app.application.scheduler_service import (MonitorConfig,
                                                       MonitorScheduler)

# 2026-11-26 是周四；2026-11-28 是周六
THU = lambda h, m=0: datetime(2026, 11, 26, h, m)      # noqa: E731
SAT = lambda h, m=0: datetime(2026, 11, 28, h, m)      # noqa: E731


class FakeResult:
    def __init__(self, events=3, notice=1, industry=2, auto=1):
        self._d = dict(events_detected=events, notice_events=notice,
                       industry_events={"events_detected": industry},
                       auto_reports=[{}] * auto, stocks_scanned=7,
                       failed_stocks=[], note="")

    def to_dict(self):
        return dict(self._d)


class FakeRefresh:
    """记录每次被调用时收到的参数，用于验证「哪一档跑了」。"""

    def __init__(self, boom: bool = False):
        self.calls = []
        self.boom = boom

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.boom:
            raise RuntimeError("数据源挂了")
        return FakeResult()


def make(refresh=None, **cfg):
    refresh = refresh or FakeRefresh()
    conf = MonitorConfig(**{**dict(
        enabled=True, interval_minutes=30, light_start="09:00",
        light_end="15:00", full_slots=("16:00", "21:00"),
        full_grace_minutes=10, detect_days=180, skip_weekends=True,
        tick_seconds=30), **cfg})
    return MonitorScheduler(refresh, config=conf, log=None), refresh


# ============================================================
# 1. 排班判断
# ============================================================
def test_disabled_never_runs():
    sch, _ = make(enabled=False)
    assert sch.should_run(THU(10)) is None
    assert sch.tick(THU(10)) is None


def test_weekend_skipped():
    sch, _ = make()
    assert sch.should_run(SAT(10)) is None
    assert sch.should_run(SAT(16)) is None


def test_weekend_can_be_allowed():
    sch, _ = make(skip_weekends=False)
    assert sch.should_run(SAT(10)) == ("light", None)


def test_light_first_run_in_window():
    sch, _ = make()
    assert sch.should_run(THU(9, 30)) == ("light", None)


def test_outside_window_does_not_run():
    sch, _ = make()
    assert sch.should_run(THU(8, 0)) is None      # 窗口前
    assert sch.should_run(THU(15, 0)) is None     # 窗口右端点不含
    assert sch.should_run(THU(17, 30)) is None    # 非完整档时点


def test_light_respects_interval():
    sch, _ = make()
    sch.tick(THU(9, 0))
    # 刚跑过 -> 不够 30 分钟，不跑
    assert sch.should_run(THU(9, 10)) is None
    assert sch.should_run(THU(9, 29)) is None
    # 满 30 分钟 -> 再跑
    assert sch.should_run(THU(9, 30)) == ("light", None)


def test_full_slot_fires_once_per_day():
    sch, _ = make()
    assert sch.should_run(THU(16, 0)) == ("full", "16:00")
    sch.tick(THU(16, 0))
    assert sch.should_run(THU(16, 1)) is None          # 同一天同档只跑一次
    assert sch.should_run(THU(21, 0)) == ("full", "21:00")   # 另一个时点仍可跑


def test_full_grace_window():
    sch, _ = make(full_grace_minutes=10)
    # 线程被卡住、16:07 才 tick 到，仍应补跑
    assert sch.should_run(THU(16, 7)) == ("full", "16:00")
    # 超过宽限就不补了（避免 16:30 才跑一次「收盘档」）
    assert sch.should_run(THU(16, 15)) is None


def test_full_slot_takes_priority_over_light():
    sch, _ = make(full_slots=("10:00",))
    assert sch.should_run(THU(10, 0)) == ("full", "10:00")


# ============================================================
# 2. 两种档位的参数（关键：轻量档不能碰新闻/公告/财务）
# ============================================================
def test_light_profile_skips_news_and_notices():
    sch, refresh = make()
    sch.tick(THU(9, 30))
    kw = refresh.calls[-1]
    assert kw["include_news"] is False
    assert kw["include_notices"] is False
    assert kw["include_financials"] is False
    assert kw["include_industries"] is True      # 行业指数很便宜，留着
    assert kw["prune"] is False
    assert kw["detect_days"] == 180


def test_full_profile_includes_everything():
    sch, refresh = make()
    sch.tick(THU(16, 0))
    kw = refresh.calls[-1]
    assert kw["include_news"] is True
    assert kw["include_notices"] is True
    assert kw["include_financials"] is True
    assert kw["include_industries"] is True
    assert kw["prune"] is True


# ============================================================
# 3. 执行与状态
# ============================================================
def test_tick_records_result():
    sch, _ = make()
    rec = sch.tick(THU(9, 30))
    assert rec["ok"] is True
    assert rec["profile"] == "light"
    assert rec["events_detected"] == 3
    assert rec["industry_events"] == 2
    assert rec["auto_reports"] == 1
    assert "finished_at" in rec
    st = sch.status()
    assert st["last_run"]["profile"] == "light"
    assert st["enabled"] is True
    assert st["interval_minutes"] == 30


def test_failure_is_recorded_not_raised():
    sch, _ = make(refresh=FakeRefresh(boom=True))
    rec = sch.tick(THU(9, 30))
    assert rec["ok"] is False
    assert "RuntimeError" in rec["error"]
    # 失败也要更新 _last_light，避免每 30 秒重试把数据源打穿
    assert sch.should_run(THU(9, 35)) is None


def test_run_now_bypasses_schedule():
    sch, refresh = make()
    # 周日的 03:00，正常排班绝不会跑
    rec = sch.run_now("full")
    assert rec["ok"] is True
    assert rec["profile"] == "full"
    assert refresh.calls[-1]["include_news"] is True


def test_run_now_rejects_unknown_profile():
    sch, _ = make()
    rec = sch.run_now("whatever")
    assert rec["profile"] == "light"      # 非法值退回 light，不报错


def test_status_has_next_run():
    sch, _ = make()
    st = sch.status()
    assert st["next_run_at"] is not None
    assert st["full_slots"] == ["16:00", "21:00"]


def test_history_capped():
    sch, _ = make(interval_minutes=5)
    for i in range(25):
        sch.tick(THU(9, 0) + timedelta(minutes=5 * i))
    assert len(sch.status()["history"]) <= 5


# ============================================================
# 4. 配置解析
# ============================================================
def test_config_from_env(monkeypatch):
    monkeypatch.setenv("MONITOR_ENABLED", "false")
    monkeypatch.setenv("MONITOR_INTERVAL_MINUTES", "45")
    monkeypatch.setenv("MONITOR_LIGHT_START", "10:00")
    monkeypatch.setenv("MONITOR_FULL_SLOTS", "15:30, 20:00 ,bad")
    cfg = MonitorConfig.from_env()
    assert cfg.enabled is False
    assert cfg.interval_minutes == 45
    assert cfg.light_start == "10:00"
    assert cfg.full_slots == ("15:30", "20:00")     # 非法项被丢掉


def test_config_interval_floor(monkeypatch):
    # 间隔太短会把数据源打穿，强制下限 5 分钟
    monkeypatch.setenv("MONITOR_INTERVAL_MINUTES", "1")
    assert MonitorConfig.from_env().interval_minutes == 5


def test_config_bad_slots_fall_back(monkeypatch):
    monkeypatch.setenv("MONITOR_FULL_SLOTS", "坏掉,xx")
    assert MonitorConfig.from_env().full_slots == ("16:00", "21:00")

# ============================================================
# 5. 巡检日志落库（重启后仍能回答「上一档跑了没有」）
# ============================================================
@pytest.fixture()
def con(tmp_path):
    c = dbmod.connect(tmp_path / "t.db")
    dbmod.init_schema(c)
    yield c
    try:
        c.close()
    except Exception:
        pass


def test_run_is_persisted(con):
    from backend.app.infrastructure.repositories.monitor_run_repository import (
        SqliteMonitorRunRepository)
    repo = SqliteMonitorRunRepository(con, log=None)
    sch, _ = make()
    sch.run_repo = repo
    rec = sch.tick(THU(10))
    assert rec["ok"] is True
    assert rec.get("run_id")

    rows = repo.list_recent(5)
    assert len(rows) == 1
    assert rows[0]["profile"] == "light"
    assert rows[0]["ok"] is True
    assert rows[0]["events_detected"] == 3


def test_history_survives_restart(con):
    """新建一个 scheduler（模拟进程重启），status 仍能从库里读到上次结果。"""
    from backend.app.infrastructure.repositories.monitor_run_repository import (
        SqliteMonitorRunRepository)
    repo = SqliteMonitorRunRepository(con, log=None)

    first, _ = make()
    first.run_repo = repo
    first.tick(THU(16))                     # 跑一次完整档

    restarted, _ = make()                   # 内存全空
    restarted.run_repo = repo
    st = restarted.status()
    assert st["last_run"] is not None
    assert st["last_run"]["profile"] == "full"
    assert st["last_run"]["slot"] == "16:00"
    assert len(st["history"]) == 1


def test_failed_run_persisted_as_not_ok(con):
    from backend.app.infrastructure.repositories.monitor_run_repository import (
        SqliteMonitorRunRepository)
    repo = SqliteMonitorRunRepository(con, log=None)
    sch, _ = make(refresh=FakeRefresh(boom=True))
    sch.run_repo = repo
    sch.tick(THU(10))
    row = repo.last()
    assert row["ok"] is False
    assert "RuntimeError" in row["error"]


def test_run_repo_prune(con):
    from backend.app.infrastructure.repositories.monitor_run_repository import (
        SqliteMonitorRunRepository)
    repo = SqliteMonitorRunRepository(con, log=None)
    repo.save(dict(profile="light", started_at="2020-01-01 09:00:00", ok=True))
    repo.save(dict(profile="light", started_at="2999-01-01 09:00:00", ok=True))
    assert repo.stats()["runs"] == 2
    assert repo.prune(keep_days=30) == 1     # 只删掉那条 2020 的
    assert repo.stats()["runs"] == 1


def test_persist_failure_does_not_break_run():
    """落库失败（比如库锁住）绝不能把巡检本身搞挂。"""
    class BoomRepo:
        def save(self, record):
            raise RuntimeError("database is locked")

    sch, _ = make()
    sch.run_repo = BoomRepo()
    rec = sch.tick(THU(10))
    assert rec["ok"] is True          # 巡检成功
    assert "run_id" not in rec        # 只是没拿到 id
