# -*- coding: utf-8 -*-
"""验证两条历史回溯通道：
   A. 财联社 get_roll_list + last_time 向前翻页（需自行计算 sign）
   B. 东财新闻列表 getNewsByColumns + page_index 深度翻页

目标：确认「新闻历史丢失」是否真的无解。
"""
import os, sys, io, time, hashlib
from datetime import datetime
from urllib.parse import urlencode

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)
LOG_PATH = os.path.join(OUT, "13_news_backfill_deep.txt")
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

log("=" * 74)
log("新闻历史回溯：财联社 / 东财 深度翻页验证")
log("=" * 74)

# ============================================================
# A. 财联社
# ============================================================
log("\n[A] 财联社 get_roll_list --- last_time 向前翻页")

CLS_URL = "https://www.cls.cn/v1/roll/get_roll_list"


def cls_sign(params: dict) -> str:
    return hashlib.md5(
        hashlib.sha1(urlencode(params).encode("utf-8")).hexdigest().encode("utf-8")
    ).hexdigest()


def cls_fetch(last_time=None, rn=20):
    params = {
        "app": "CailianpressWeb",
        "category": "",
        "last_time": int(last_time if last_time else time.time()),
        "os": "web",
        "refresh_type": "1",
        "rn": str(rn),
        "sv": "8.4.6",
    }
    params["sign"] = cls_sign(params)
    r = S.get(CLS_URL, params=params, timeout=20,
              headers={"Referer": "https://www.cls.cn/telegraph"})
    r.raise_for_status()
    return r.json()


earliest = None
total = 0
oldest_str = None
try:
    js = cls_fetch()
    items = (js.get("data") or {}).get("roll_data") or []
    log(f"    第 1 页 {len(items)} 条  errno={js.get('errno')}")
    if items:
        ts = [i.get("ctime") for i in items if i.get("ctime")]
        log(f"        {datetime.fromtimestamp(min(ts))} ~ {datetime.fromtimestamp(max(ts))}")
        earliest = min(ts)
        total += len(items)
        oldest_str = str(datetime.fromtimestamp(min(ts)))

    for page in range(2, 9):
        time.sleep(1.0)
        # last_time 往前退 1 秒，避免返回同一条
        js = cls_fetch(earliest - 1)
        items = (js.get("data") or {}).get("roll_data") or []
        if not items:
            log(f"    第 {page} 页 空，终止")
            break
        ts = [i.get("ctime") for i in items if i.get("ctime")]
        if not ts:
            break
        new_earliest = min(ts)
        log(f"    第 {page} 页 {len(items)} 条  "
            f"{datetime.fromtimestamp(new_earliest)} ~ {datetime.fromtimestamp(max(ts))}")
        total += len(items)
        if new_earliest >= earliest:
            log("        最早时间未前移 -> 翻页无效")
            break
        earliest = new_earliest
        oldest_str = str(datetime.fromtimestamp(earliest))

    span_h = (time.time() - earliest) / 3600 if earliest else 0
    log(f"    累计 {total} 条，可回溯到 {oldest_str}（约 {span_h:.1f} 小时前）")
    if total > 20 and span_h > 0.5:
        log(f"    -> ✅ 支持历史回溯；按 {total/span_h:.0f} 条/小时，翻 1 天约需 "
            f"{24*max(total/span_h,1)/20:.0f} 次请求")
    else:
        log("    -> ⚠️ 回溯能力存疑")
except Exception as e:
    log(f"    FAIL {type(e).__name__}: {str(e)[:200]}")

# ============================================================
# B. 东财深度分页
# ============================================================
log("\n[B] 东财 getNewsByColumns --- page_index 深度翻页")

EM_URL = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"


def em_page(page_index, page_size=20, column="345"):
    p = {"client": "web", "biz": "web_news_col", "column": column,
         "order": "1", "needInteractData": "0",
         "page_index": str(page_index), "page_size": str(page_size),
         "req_trace": str(int(time.time() * 1000))}
    r = S.get(EM_URL, params=p, timeout=20,
              headers={"Referer": "https://finance.eastmoney.com/"})
    r.raise_for_status()
    js = r.json()
    return (((js.get("data") or {}).get("list")) or [])


try:
    probe_pages = [1, 10, 30, 60, 120, 240]
    stamps = {}
    for pi in probe_pages:
        items = em_page(pi)
        if not items:
            log(f"    page {pi:4d}: 0 条")
            continue
        times = [str(i.get("showTime") or "")[:19] for i in items if i.get("showTime")]
        times = [t for t in times if t]
        if times:
            stamps[pi] = (min(times), max(times), len(items))
            log(f"    page {pi:4d}: {len(items)} 条  最早 {min(times)}  最晚 {max(times)}")
        time.sleep(1.0)

    if len(stamps) >= 2:
        first_pi = min(stamps)
        last_pi = max(stamps)
        d0 = datetime.fromisoformat(stamps[first_pi][0])
        d1 = datetime.fromisoformat(stamps[last_pi][0])
        days = (d0 - d1).total_seconds() / 86400
        log(f"    从 page {first_pi} 到 {last_pi}（{(last_pi-first_pi)*20} 条）"
            f"跨越 {days:.1f} 天")
        if days > 0:
            log(f"    -> 平均 {abs((last_pi-first_pi)*20/days):.0f} 条/天")
            log(f"    -> 回溯 30 天约需 page 翻到 {first_pi + int(30*days and (last_pi-first_pi)/days*30):.0f}")
except Exception as e:
    log(f"    FAIL {type(e).__name__}: {str(e)[:200]}")

log("\n" + "=" * 74)
