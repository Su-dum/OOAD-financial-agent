#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新闻回溯补齐（backfill）。

利用两个源的历史翻页能力，把过去 N 天的新闻补进库：
  东财新闻列表 —— page_index 翻页，可回溯 48+ 天
  财联社电报   —— last_time 翻页（需自算 sign）

用法：
  python scripts/backfill_news.py                      # 东财 30 天 + 财联社 7 天
  python scripts/backfill_news.py --days 48            # 东财拉到上限
  python scripts/backfill_news.py --cls-days 3 --delay 0.6
  python scripts/backfill_news.py --rebuild-links      # 只重算股票关联
  python scripts/backfill_news.py --dry-run            # 只抓不入库
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


def cutoff_str(days):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def backfill_em(con, days, page_size, column, delay, max_pages, stop_on_known,
                dry_run, log):
    cut = cutoff_str(days)
    log(f"\n=== 东财新闻列表：回溯 {days} 天（早于 {cut} 停止）===")
    total_fetched = total_new = 0
    known_streak = 0
    page = 1
    while page <= max_pages:
        rows = src.fetch_em_list(page_index=page, page_size=page_size,
                                 column=column, log=log)
        if rows is None:
            log(f"  第 {page} 页抓取失败，终止东财回溯")
            break
        if not rows:
            log(f"  第 {page} 页为空，结束")
            break

        oldest = min((r["published_at"] for r in rows if r["published_at"]), default=None)
        if not dry_run:
            st = store.ingest(con, rows, link=True, log=log,
                              source_label=f"em_list:{column}")
            total_fetched += st["fetched"]
            total_new += st["inserted"]
            if st["inserted"] == 0:
                known_streak += 1
            else:
                known_streak = 0

        log(f"  [em {page:>3}/{max_pages}] 取 {len(rows):>2} 条，最早 {oldest}"
            + (f"  (连续 {known_streak} 页全重复)" if known_streak else ""))

        if oldest and oldest < cut:
            log(f"  已越过 {cut} 边界，结束")
            break
        if stop_on_known and known_streak >= stop_on_known:
            log(f"  连续 {known_streak} 页都是已有数据，判定已补齐，结束")
            break
        page += 1
        time.sleep(delay)

    log(f"东财小计：取 {total_fetched} 条，新增 {total_new} 条")
    return total_fetched, total_new


def backfill_cls(con, days, delay, max_pages, stop_on_known, dry_run, log):
    cut = cutoff_str(days)
    log(f"\n=== 财联社电报：回溯 {days} 天（早于 {cut} 停止）===")
    total_fetched = total_new = 0
    known_streak = 0
    last_time = None
    page = 1
    while page <= max_pages:
        rows = src.fetch_cls_page(last_time=last_time, rn=20, log=log)
        if rows is None:
            log(f"  第 {page} 页抓取失败，终止财联社回溯")
            break
        if not rows:
            log(f"  第 {page} 页为空，结束")
            break

        stamps = [r["published_at"] for r in rows if r["published_at"]]
        oldest = min(stamps) if stamps else None
        if not dry_run:
            st = store.ingest(con, rows, link=True, log=log, source_label="cls")
            total_fetched += st["fetched"]
            total_new += st["inserted"]
            if st["inserted"] == 0:
                known_streak += 1
            else:
                known_streak = 0

        log(f"  [cls {page:>3}/{max_pages}] 取 {len(rows):>2} 条，最早 {oldest}"
            + (f"  (连续 {known_streak} 页全重复)" if known_streak else ""))

        if oldest and oldest < cut:
            log(f"  已越过 {cut} 边界，结束")
            break
        if stop_on_known and known_streak >= stop_on_known:
            log(f"  连续 {known_streak} 页都是已有数据，结束")
            break
        if not oldest:
            break
        last_time = int(datetime.strptime(oldest, "%Y-%m-%d %H:%M:%S").timestamp()) - 1
        page += 1
        time.sleep(delay)

    log(f"财联社小计：取 {total_fetched} 条，新增 {total_new} 条")
    return total_fetched, total_new


def main():
    ap = argparse.ArgumentParser(description="新闻历史回溯补齐")
    ap.add_argument("--days", type=int, default=30, help="东财回溯天数（默认 30）")
    ap.add_argument("--cls-days", type=int, default=7, help="财联社回溯天数（默认 7）")
    ap.add_argument("--page-size", type=int, default=20)
    ap.add_argument("--column", default="345", help="东财栏目号")
    ap.add_argument("--delay", type=float, default=0.8, help="请求间隔秒")
    ap.add_argument("--max-pages", type=int, default=400)
    ap.add_argument("--cls-max-pages", type=int, default=300)
    ap.add_argument("--stop-on-known", type=int, default=25,
                    help="连续多少页全为重复数据即停止（增量跑用，0=关闭）")
    ap.add_argument("--no-em", action="store_true")
    ap.add_argument("--no-cls", action="store_true")
    ap.add_argument("--auto", action="store_true",
                    help="根据库里最新新闻自动计算需要补多少天，无需手填 --days")
    ap.add_argument("--rebuild-links", action="store_true",
                    help="只对已有新闻重算股票关联，不抓新数据")
    ap.add_argument("--dry-run", action="store_true", help="只抓不入库")
    args = ap.parse_args()

    log = print
    t0 = time.time()
    con = dbmod.connect()
    dbmod.init_schema(con)
    dbmod.sync_stocks(con)

    if args.auto and not args.rebuild_links:
        last = con.execute("SELECT MAX(published_at) FROM news").fetchone()[0]
        if last:
            gap = (datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).days
        else:
            gap = args.days
        # 东财能回溯约 200 天；多补 2 天做重叠，避免边界漏采
        args.days = max(1, min(gap + 2, 200))
        # 财联社翻页成本高（约 28 页/天），只补最近一段
        args.cls_days = max(1, min(gap + 1, 14))
        log(f"[auto] 库中最新新闻 {last or '（空库）'}，已断 {gap} 天")
        log(f"[auto] -> 东财补 {args.days} 天，财联社补 {args.cls_days} 天")
        if gap >= 190:
            log("[auto] ⚠️ 断档已接近东财回溯上限（约 200 天），更早的数据会永久丢失")

    if args.rebuild_links:
        store.rebuild_links(con, log=log)
        print_summary(con, log, time.time() - t0)
        return

    if args.dry_run:
        log("*** dry-run：只抓不入库 ***")

    if not args.no_em:
        backfill_em(con, args.days, args.page_size, args.column, args.delay,
                    args.max_pages, args.stop_on_known, args.dry_run, log)
    if not args.no_cls:
        backfill_cls(con, args.cls_days, args.delay, args.cls_max_pages,
                     args.stop_on_known, args.dry_run, log)

    print_summary(con, log, time.time() - t0)


def print_summary(con, log, elapsed):
    s = store.summary(con)
    log("\n" + "=" * 68)
    log("新闻库现状")
    log("=" * 68)
    log(f"  新闻总数      {s['news']:,}")
    log(f"  时间范围      {s['earliest']}  ~  {s['latest']}")
    log(f"  关联记录      {s['links']:,} 条（覆盖 {s['linked_news']:,} 篇新闻）")
    log(f"  涉及股票      {s['stocks_in_news']:,} 只")
    log(f"  耗时          {elapsed:.1f}s")

    log("\n  按来源：")
    for r in con.execute("SELECT source, COUNT(*) c FROM news GROUP BY source "
                         "ORDER BY c DESC"):
        log(f"    {r['source']:<10} {r['c']:>7,}")

    log("\n  关联最多的 10 只股票：")
    for r in con.execute(
            "SELECT ns.stock_code, ns.stock_name, COUNT(*) c FROM news_stock ns "
            "GROUP BY ns.stock_code ORDER BY c DESC LIMIT 10"):
        log(f"    {r['stock_code']} {str(r['stock_name'] or ''):<8} {r['c']:>5} 条")

    log("\n  最近 5 条已关联新闻：")
    for r in con.execute(
            "SELECT n.published_at, n.title, GROUP_CONCAT(ns.stock_name,'/') names "
            "FROM news n JOIN news_stock ns ON ns.news_id=n.id "
            "GROUP BY n.id ORDER BY n.published_at DESC LIMIT 5"):
        log(f"    {r['published_at']} [{r['names']}] {r['title'][:40]}")


if __name__ == "__main__":
    main()
