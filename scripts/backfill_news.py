#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新闻回溯补齐（CLI）。

核心逻辑在 `backend/app/application/news_service.py::NewsIngestService`，
本脚本只是它的命令行外壳——API 的「更新数据」按钮用的是同一份实现。

用法：
  python scripts/backfill_news.py                    # 自动按断档天数补齐
  python scripts/backfill_news.py --days 30          # 东财补 30 天
  python scripts/backfill_news.py --cls-days 7       # 财联社补 7 天
  python scripts/backfill_news.py --rebuild-links    # 只重算股票关联
  python scripts/backfill_news.py --prune            # 按保留策略清理旧数据
  python scripts/backfill_news.py --stats            # 只看库现状
"""
import os
import sys
import time
import argparse
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.app import db as dbmod                                   # noqa: E402
from backend.app.application.maintenance_service import (              # noqa: E402
    MaintenanceService, RetentionPolicy)
from backend.app.application.news_service import NewsIngestService     # noqa: E402
from backend.app.infrastructure.repositories.news_repository import (   # noqa: E402
    SqliteNewsRepository)


def print_stats(con, log):
    repo = SqliteNewsRepository(con, log=lambda *a: None)
    s = repo.stats()
    log("=" * 60)
    log("新闻库现状")
    log("=" * 60)
    log(f"  新闻总数   {s['news']:,}")
    log(f"  时间范围   {s['earliest']}  ~  {s['latest']}")
    log(f"  关联记录   {s['links']:,}（覆盖 {s['linked_news']:,} 篇 / "
        f"{s['stocks_in_news']:,} 只股票）")
    log("\n  按来源：")
    for r in con.execute("SELECT source, COUNT(*) c FROM news GROUP BY source "
                         "ORDER BY c DESC"):
        log(f"    {r['source']:<10} {r['c']:>7,}")
    log("\n  保留策略：")
    for k, v in RetentionPolicy().describe().items():
        log(f"    {k:<14} {v}")


def main():
    ap = argparse.ArgumentParser(description="新闻回溯补齐 / 清理")
    ap.add_argument("--auto", action="store_true",
                    help="按库里最新新闻自动计算需要补多少天")
    ap.add_argument("--days", type=int, default=30, help="东财回溯天数")
    ap.add_argument("--cls-days", type=int, default=7, help="财联社回溯天数")
    ap.add_argument("--page-size", type=int, default=20)
    ap.add_argument("--max-pages", type=int, default=400)
    ap.add_argument("--cls-max-pages", type=int, default=300)
    ap.add_argument("--delay", type=float, default=0.8)
    ap.add_argument("--stop-on-known", type=int, default=25)
    ap.add_argument("--no-em", action="store_true")
    ap.add_argument("--no-cls", action="store_true")
    ap.add_argument("--rebuild-links", action="store_true")
    ap.add_argument("--prune", action="store_true", help="按保留策略清理旧数据")
    ap.add_argument("--prune-dry-run", action="store_true")
    ap.add_argument("--stats", action="store_true", help="只看库现状")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    log = (lambda *a, **k: None) if args.quiet else print
    con = dbmod.connect()
    dbmod.init_schema(con)
    dbmod.sync_stocks(con)
    repo = SqliteNewsRepository(con, log=log)

    if args.stats:
        print_stats(con, print)
        return

    if args.rebuild_links:
        n = repo.rebuild_links()
        print(f"重建关联：{n} 条")
        print_stats(con, print)
        return

    if args.prune or args.prune_dry_run:
        MaintenanceService(con, log=print).prune(dry_run=args.prune_dry_run)
        print_stats(con, print)
        return

    t0 = time.time()
    svc = NewsIngestService(repo, log=log, delay=args.delay)

    if args.auto:
        last = con.execute("SELECT MAX(published_at) FROM news").fetchone()[0]
        gap = 0
        if last:
            gap = (datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).days
        args.days = max(1, min(gap + 2, 200))
        args.cls_days = max(1, min(gap + 1, 14))
        print(f"[auto] 库中最新 {last or '（空库）'}，已断 {gap} 天")
        print(f"[auto] -> 东财补 {args.days} 天，财联社补 {args.cls_days} 天")
        if gap >= 190:
            print("[auto] ⚠️ 断档接近东财回溯上限（约 200 天），更早的数据会永久丢失")

    if not args.no_em:
        st = svc.backfill_em(days=args.days, page_size=args.page_size,
                             max_pages=args.max_pages,
                             stop_on_known=args.stop_on_known)
        print(f"东财：{st.pages} 页 / 取 {st.fetched} / 新增 {st.inserted} "
              f"/ 重复 {st.skipped}（{st.stopped_by}）")
    if not args.no_cls:
        st = svc.backfill_cls(days=args.cls_days, max_pages=args.cls_max_pages,
                              stop_on_known=args.stop_on_known)
        print(f"财联社：{st.pages} 页 / 取 {st.fetched} / 新增 {st.inserted} "
              f"/ 重复 {st.skipped}（{st.stopped_by}）")

    print(f"\n耗时 {time.time()-t0:.1f}s")
    print_stats(con, print)


if __name__ == "__main__":
    main()
