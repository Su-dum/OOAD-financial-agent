# -*- coding: utf-8 -*-
"""测「回溯窗口」有多深：多久不采，还能补回来？

方法：不要一页页翻（太慢），而是直接指定「早于 N 天前」的时间戳请求一页，
看还能不能拿到数据。这直接给出每个源的可回溯上限。
"""
import os, sys, io, time, hashlib
from datetime import datetime, timedelta
from urllib.parse import urlencode

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)
LOG_PATH = os.path.join(OUT, "14_backfill_horizon.txt")
open(LOG_PATH, "w", encoding="utf-8").close()


def log(s=""):
    line = str(s)
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA})
NOW = datetime.now()

# ============================================================
# A. 财联社：指定 last_time 为 N 天前，看还有没有数据
# ============================================================
log("=" * 70)
log("回溯窗口深度测试   今天 = " + NOW.strftime("%Y-%m-%d %H:%M"))
log("=" * 70)

CLS_URL = "https://www.cls.cn/v1/roll/get_roll_list"


def cls_sign(params):
    return hashlib.md5(
        hashlib.sha1(urlencode(params).encode("utf-8")).hexdigest().encode("utf-8")
    ).hexdigest()


def cls_at(ts):
    params = {"app": "CailianpressWeb", "category": "",
              "last_time": int(ts), "os": "web", "refresh_type": "1",
              "rn": "20", "sv": "8.4.6"}
    params["sign"] = cls_sign(params)
    r = S.get(CLS_URL, params=params, timeout=25,
              headers={"Referer": "https://www.cls.cn/telegraph"})
    r.raise_for_status()
    return ((r.json().get("data") or {}).get("roll_data")) or []


log("\n[A] 财联社电报 可回溯多深")
for days in (1, 3, 7, 10, 14, 20, 30, 60, 90, 180):
    ts = (NOW - timedelta(days=days)).timestamp()
    try:
        items = cls_at(ts)
        if items:
            stamps = [i.get("ctime") for i in items if i.get("ctime")]
            if stamps:
                lo = datetime.fromtimestamp(min(stamps))
                hi = datetime.fromtimestamp(max(stamps))
                log(f"    {days:>3} 天前: {len(items):>2} 条  {lo:%m-%d %H:%M} ~ {hi:%m-%d %H:%M}  ✅")
            else:
                log(f"    {days:>3} 天前: {len(items)} 条但无时间戳")
        else:
            log(f"    {days:>3} 天前: 0 条  ❌ 拿不到")
    except Exception as e:
        log(f"    {days:>3} 天前: FAIL {type(e).__name__} {str(e)[:60]}")
    time.sleep(0.7)

# ============================================================
# B. 东财：翻到很深的页码，看还有没有数据
# ============================================================
log("\n[B] 东财新闻列表 可翻多深（20 条/页）")
EM_URL = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"


def em_at(page):
    p = {"client": "web", "biz": "web_news_col", "column": "345",
         "order": "1", "needInteractData": "0",
         "page_index": str(page), "page_size": "20",
         "req_trace": str(int(time.time() * 1000))}
    r = S.get(EM_URL, params=p, timeout=25,
              headers={"Referer": "https://finance.eastmoney.com/"})
    r.raise_for_status()
    return ((r.json().get("data") or {}).get("list")) or []


for page in (300, 400, 600, 800, 1200, 2000):
    try:
        items = em_at(page)
        if not items:
            log(f"    page {page:>5}: 0 条  ❌ 到底了")
            continue
        times = [str(i.get("showTime"))[:19] for i in items if i.get("showTime")]
        if times:
            d = datetime.fromisoformat(min(times))
            age = (NOW - d).days
            log(f"    page {page:>5}: {len(items):>2} 条  最早 {min(times)}  "
                f"（约 {age} 天前）✅")
        else:
            log(f"    page {page:>5}: {len(items)} 条但无时间")
    except Exception as e:
        log(f"    page {page:>5}: FAIL {type(e).__name__} {str(e)[:60]}")
    time.sleep(0.7)

log("\n" + "=" * 70)
