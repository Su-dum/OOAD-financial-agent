#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""实时新闻采集。

注意：这不是「开机自动运行」。它只是一个进程，你不启动它就不跑，
电脑关机就断。所以配套用 backfill_news.py 定期补洞——

  日常：开机时跑本脚本（或挂 Windows 任务计划）
  兜底：每周跑一次 scripts/backfill_news.py 把缺口补上

用法：
  python scripts/run_collector.py --once          # 只跑一轮（调试）
  python scripts/run_collector.py                 # 每 300 秒一轮，前台常驻
  python scripts/run_collector.py --gap-fill 1    # 每轮前先补最近 1 天的洞
"""
import os
import sys
import time
import argparse
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.app import db as dbmod                      # noqa: E402
from backend.app.infrastructure.providers import news_sources as src    # noqa: E402
from backend.app.infrastructure.repositories import news_store as store     # noqa: E402


def one_round(con, gap_fill_days=0, log=print):
    log(f"\n--- 本轮开始 {datetime.now():%Y-%m-%d %H:%M:%S} ---")

    if gap_fill_days > 0:
        last = con.execute("SELECT MAX(published_at) FROM news").fetchone()[0]
        need = True
        if last:
            age_h = (datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
            need = age_h > 0.5
            log(f"  库中最新新闻 {last}（{age_h:.1f} 小时前）"
                + ("，需要补洞" if need else "，无需补洞"))
        if need:
            from backfill_news import backfill_em
            backfill_em(con, gap_fill_days, 20, "345", 0.8,
                        max_pages=60, stop_on_known=10, dry_run=False, log=log)

    for name, fn in (("东财快讯", src.fetch_em_flash), ("财联社电报", src.fetch_cls_snapshot)):
        rows = fn(log=log)
        if rows is None:
            log(f"  {name}: 抓取失败，跳过")
            continue
        log(f"  {name}:")
        store.ingest(con, rows, link=True, log=log, source_label=name)

    s = store.summary(con)
    log(f"  累计：{s['news']:,} 条新闻 / {s['links']:,} 条关联 / "
        f"{s['stocks_in_news']:,} 只股票")


def main():
    ap = argparse.ArgumentParser(description="实时新闻采集")
    ap.add_argument("--interval", type=int, default=300, help="轮询间隔秒（默认 300）")
    ap.add_argument("--once", action="store_true", help="只跑一轮")
    ap.add_argument("--gap-fill", type=int, default=0,
                    help="每轮前先回溯补齐最近 N 天（0=关闭）")
    ap.add_argument("--max-rounds", type=int, default=0, help="跑多少轮后退出（0=无限）")
    args = ap.parse_args()

    con = dbmod.connect()
    dbmod.init_schema(con)
    dbmod.sync_stocks(con)

    if args.once:
        one_round(con, args.gap_fill)
        return

    rounds = 0
    print(f"实时采集启动，间隔 {args.interval}s，Ctrl+C 退出")
    while True:
        try:
            one_round(con, args.gap_fill)
        except KeyboardInterrupt:
            print("\n已停止")
            break
        except Exception as e:
            print(f"[warn] 本轮异常 {type(e).__name__}: {e}")
        rounds += 1
        if args.max_rounds and rounds >= args.max_rounds:
            print(f"已跑满 {rounds} 轮，退出")
            break
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n已停止")
            break


if __name__ == "__main__":
    main()
