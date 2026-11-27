# -*- coding: utf-8 -*-
"""定时监控调度（让 B1 的「监控」从按需刷新变成自动巡检）。

## 为什么必须分「轻量档」和「完整档」

本机实测（7 只自选股 + 3 个监控行业）：

    完整刷新  18.9s   外部请求约 20 次（新闻 9 页 + 公告 7 只 + 行情 + 行业指数）
    轻量刷新   1.8s   外部请求约 3 次（行情与行业指数**全部命中 CSV 缓存**）

`BasePriceProvider` 的缓存 key 是「源+代码+复权+起止日」，同一天内重复请求直接命中磁盘，
所以盘中高频巡检的真实外部流量接近于零。真正贵的是**新闻回溯**和**公告全量**，
而这两者都是「一天补一次就够」的性质（东财新闻可翻 200 天、公告可回补 400 天）。

因此排班：

    盘中  09:00–15:00   每 30 分钟   轻量档：只检测行情事件 + 行业事件（不碰新闻/公告）
    盘后  16:00 / 21:00  各一次      完整档：补当天新闻与公告 → 检测 → 自动调查 → 裁剪

一天外部请求 ≈ 12×0 + 2×20 = **40 次**，比人工反复点「更新数据」还少。

## 为什么不引入 APScheduler

只有两个固定时点 + 一个等间隔，用 `threading.Thread` + `Event.wait` 就够了。
少一个依赖，也让 `should_run(now)` 成为**纯函数**——测试可以传任意时间点，不用真的等 30 分钟。

## 线程安全

巡检会碰 SQLite。已有的 `db.connect` 用 `check_same_thread=False` + WAL + busy_timeout
（见 `tests/test_threading.py`），所以在后台线程里跑刷新是安全的。
另外用非阻塞锁防重入：上一次还没跑完就跳过本次，避免慢请求堆叠。
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional


def _env_bool(name: str, default: bool) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on", "y")


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or "").strip())
    except (TypeError, ValueError):
        return default


def _to_min(hm: str) -> Optional[int]:
    try:
        h, m = str(hm).strip().split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


@dataclass(frozen=True)
class MonitorConfig:
    """定时巡检排班（全部可用环境变量覆盖，见 `.env.example`）。"""

    enabled: bool = True
    interval_minutes: int = 30          # 盘中轻量档间隔
    light_start: str = "09:00"          # 轻量窗口起（含）
    light_end: str = "15:00"            # 轻量窗口止（不含）
    full_slots: tuple = ("16:00", "21:00")   # 完整档固定时点
    full_grace_minutes: int = 10        # 时点后多少分钟内仍算命中（休眠/卡顿容忍）
    detect_days: int = 180              # 事件回看天数（z-score 需要 61 个历史点）
    skip_weekends: bool = True
    tick_seconds: int = 30              # 后台线程多久检查一次排班

    @classmethod
    def from_env(cls) -> "MonitorConfig":
        slots = tuple(
            s.strip() for s in
            (os.environ.get("MONITOR_FULL_SLOTS") or "16:00,21:00").split(",")
            if s.strip() and _to_min(s) is not None
        ) or ("16:00", "21:00")
        return cls(
            enabled=_env_bool("MONITOR_ENABLED", True),
            interval_minutes=max(5, _env_int("MONITOR_INTERVAL_MINUTES", 30)),
            light_start=(os.environ.get("MONITOR_LIGHT_START") or "09:00").strip(),
            light_end=(os.environ.get("MONITOR_LIGHT_END") or "15:00").strip(),
            full_slots=slots,
            full_grace_minutes=max(1, _env_int("MONITOR_FULL_GRACE_MINUTES", 10)),
            detect_days=max(5, _env_int("MONITOR_DETECT_DAYS", 180)),
            skip_weekends=_env_bool("MONITOR_SKIP_WEEKENDS", True),
            tick_seconds=max(5, _env_int("MONITOR_TICK_SECONDS", 30)),
        )

    def describe(self) -> dict:
        return dict(
            enabled=self.enabled,
            interval_minutes=self.interval_minutes,
            light_window=dict(start=self.light_start, end=self.light_end),
            full_slots=list(self.full_slots),
            detect_days=self.detect_days,
            skip_weekends=self.skip_weekends,
            tick_seconds=self.tick_seconds,
        )


class MonitorScheduler:
    """定时巡检器。

    职责单一：**决定「现在该跑哪一档」**，然后交给 `RefreshService`。
    它自己不碰数据源，也不做事件检测——那些都在 refresh 里，手工刷新与定时巡检共用同一条代码路径，
    不会出现「按钮跑一套、定时跑另一套」的行为漂移。
    """

    def __init__(self, refresh, config: Optional[MonitorConfig] = None,
                 log: Callable = print, now_fn: Optional[Callable] = None,
                 run_repo=None):
        self.refresh = refresh
        self.config = config or MonitorConfig.from_env()
        self.log = log
        self._now = now_fn or datetime.now
        # run_repo：把每次巡检落库。没有它就退化成「只在内存里记」，
        # 重启后无法回答「上一档跑了没有」——生产装配一定给。
        self.run_repo = run_repo

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._last_light: Optional[datetime] = None
        self._full_done: set = set()          # {(date_iso, slot)}
        self._running_profile: Optional[str] = None
        self._last_run: Optional[dict] = None
        self._history: list = []              # 最近几次的摘要（给状态接口）

    # ---------------------------------------------------------------- 排班
    def _in_light_window(self, cur_min: int) -> bool:
        lo = _to_min(self.config.light_start)
        hi = _to_min(self.config.light_end)
        if lo is None or hi is None:
            return False
        return lo <= cur_min < hi

    def should_run(self, now: Optional[datetime] = None):
        """返回 ('light'|'full', slot) 或 None。**纯判断，无副作用**，便于单测。"""
        now = now or self._now()
        cfg = self.config
        if not cfg.enabled:
            return None
        if cfg.skip_weekends and now.weekday() >= 5:      # 0=周一 … 6=周日
            return None

        cur = now.hour * 60 + now.minute

        # 1) 完整档：固定时点，给一段宽限（线程被卡住时晚几分钟也能补上）
        for slot in cfg.full_slots:
            s = _to_min(slot)
            if s is None:
                continue
            if s <= cur < s + cfg.full_grace_minutes:
                if (now.date().isoformat(), slot) not in self._full_done:
                    return ("full", slot)

        # 2) 轻量档：窗口内且距上次够久
        if self._in_light_window(cur):
            if self._last_light is None:
                return ("light", None)
            gap = (now - self._last_light).total_seconds() / 60.0
            if gap >= cfg.interval_minutes:
                return ("light", None)
        return None

    def _next_run(self, now: Optional[datetime] = None) -> Optional[str]:
        """粗算下一次触发时间，仅用于界面展示。"""
        now = now or self._now()
        if not self.config.enabled:
            return None
        for i in range(0, 7 * 24 * 60):
            t = now + timedelta(minutes=i)
            if self.config.skip_weekends and t.weekday() >= 5:
                continue
            cur = t.hour * 60 + t.minute
            if i > 0:
                cand = self.should_run(t)
                if cand is not None:
                    return t.strftime("%Y-%m-%d %H:%M")
            elif self.should_run(t) is not None:
                return t.strftime("%Y-%m-%d %H:%M")
        return None

    # ---------------------------------------------------------------- 执行
    def _profile_kwargs(self, profile: str) -> dict:
        d = self.config.detect_days
        if profile == "full":
            return dict(news_days=2, max_pages=12, include_news=True,
                        detect_days=d, include_notices=True,
                        include_financials=True, include_industries=True,
                        prune=True)
        return dict(news_days=0.5, max_pages=1, include_news=False,
                    detect_days=d, include_notices=False,
                    include_financials=False, include_industries=True,
                    prune=False)

    def _run(self, profile: str, now: datetime, slot: Optional[str]) -> dict:
        t0 = time.time()
        self._running_profile = profile
        record = dict(profile=profile, slot=slot,
                      started_at=now.strftime("%Y-%m-%d %H:%M:%S"))
        try:
            res = self.refresh.run(**self._profile_kwargs(profile))
            body = res.to_dict() if hasattr(res, "to_dict") else dict(res)
            record.update(ok=True, elapsed_sec=round(time.time() - t0, 1),
                          events_detected=body.get("events_detected", 0),
                          notice_events=body.get("notice_events", 0),
                          industry_events=(body.get("industry_events") or {}).get(
                              "events_detected", 0),
                          auto_reports=len(body.get("auto_reports") or []),
                          stocks_scanned=body.get("stocks_scanned", 0),
                          failed_stocks=body.get("failed_stocks") or [],
                          note=body.get("note") or "")
            if self.log:
                self.log(f"  [monitor] {profile} 档完成 "
                         f"{record['elapsed_sec']}s：事件 "
                         f"{record['events_detected']}（公告 "
                         f"{record['notice_events']}）· 行业 "
                         f"{record['industry_events']} · 自动报告 "
                         f"{record['auto_reports']}")
        except Exception as e:                            # noqa: BLE001
            record.update(ok=False, elapsed_sec=round(time.time() - t0, 1),
                          error=f"{type(e).__name__}: {e}")
            if self.log:
                self.log(f"  [monitor] {profile} 档失败: {type(e).__name__}: {e}")
        finally:
            self._running_profile = None
            if profile == "light":
                self._last_light = now
            elif slot is not None:
                self._full_done.add((now.date().isoformat(), slot))
            record["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._last_run = record
            self._history.append(record)
            del self._history[:-20]
            self._persist(record)
        return record

    def _persist(self, record: dict) -> None:
        """把这次巡检落库；落库失败绝不能影响巡检本身。"""
        if self.run_repo is None:
            return
        try:
            record["run_id"] = self.run_repo.save(record)
        except Exception as e:                            # noqa: BLE001
            if self.log:
                self.log(f"  [monitor] 巡检日志落库失败: {type(e).__name__}")

    def tick(self, now: Optional[datetime] = None) -> Optional[dict]:
        """检查排班，该跑就跑。返回本次结果（没跑返回 None）。"""
        now = now or self._now()
        decision = self.should_run(now)
        if decision is None:
            return None
        profile, slot = decision
        if not self._lock.acquire(blocking=False):
            if self.log:
                self.log("  [monitor] 上一次巡检未结束，跳过本轮")
            return None
        try:
            return self._run(profile, now, slot)
        finally:
            self._lock.release()

    def run_now(self, profile: str = "light") -> dict:
        """手动触发一次（前端「立即巡检」按钮 / 演示用），不看排班。"""
        profile = profile if profile in ("light", "full") else "light"
        if not self._lock.acquire(blocking=False):
            return dict(ok=False, profile=profile,
                        error="上一次巡检还在进行，请稍后再试")
        try:
            return self._run(profile, self._now(), slot=None)
        finally:
            self._lock.release()

    # ---------------------------------------------------------------- 线程
    def _loop(self) -> None:
        cfg = self.config
        if self.log:
            self.log(f"  [monitor] 定时巡检已启动：轻量每 {cfg.interval_minutes} 分钟"
                     f"（{cfg.light_start}–{cfg.light_end}）、完整 {list(cfg.full_slots)}"
                     f"{'、仅工作日' if cfg.skip_weekends else ''}")
        while not self._stop.wait(cfg.tick_seconds):
            try:
                self.tick()
            except Exception as e:                        # noqa: BLE001
                if self.log:
                    self.log(f"  [monitor] 巡检异常: {type(e).__name__}: {e}")

    def start(self) -> bool:
        if not self.config.enabled:
            if self.log:
                self.log("  [monitor] 定时巡检已关闭（MONITOR_ENABLED=false）")
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="monitor-scheduler")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=3)

    # ---------------------------------------------------------------- 状态
    def status(self) -> dict:
        # 优先读库里的历史：进程重启后仍能回答「上一档跑了没有」
        persisted = None
        if self.run_repo is not None:
            try:
                persisted = self.run_repo.list_recent(10)
            except Exception as e:                        # noqa: BLE001
                if self.log:
                    self.log(f"  [monitor] 巡检日志读取失败: {type(e).__name__}")
                persisted = None
        last = self._last_run or (persisted[0] if persisted else None)
        return dict(
            **self.config.describe(),
            running_profile=self._running_profile,
            last_run=last,
            next_run_at=self._next_run(),
            history=(persisted[:5] if persisted else self._history[-5:]),
        )
