# -*- coding: utf-8 -*-
"""新闻数据源。每个函数返回统一结构的 list[dict]：
   {source, channel, title, content, published_at, url}

支持两类：
  快照（实时采集）：stock_info_global_em / cls 首页 —— 只有当下几十条
  翻页（回溯补齐）：东财 getNewsByColumns(page_index) / 财联社 get_roll_list(last_time)
"""
import time
import hashlib
from datetime import datetime
from urllib.parse import urlencode

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": UA})


def _retry(fn, name, attempts=3, base=3, log=print):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            wait = base * (2 ** i)
            log(f"    [retry {i+1}/{attempts}] {name}: {type(e).__name__} {str(e)[:70]} -> {wait}s")
            if i < attempts - 1:
                time.sleep(wait)
    log(f"    [FAIL] {name} 重试耗尽")
    return None


def _iso(v):
    """把各种时间表示规范成 'YYYY-MM-DD HH:MM:SS'"""
    if v is None:
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        try:
            return datetime.fromtimestamp(int(v)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt) + 4].strip(), fmt).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


# ============================================================
# 东财新闻列表（可回溯）
# ============================================================
EM_LIST_URL = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"


def fetch_em_list(page_index=1, page_size=20, column="345", log=print):
    def _call():
        p = {"client": "web", "biz": "web_news_col", "column": column,
             "order": "1", "needInteractData": "0",
             "page_index": str(page_index), "page_size": str(page_size),
             "req_trace": str(int(time.time() * 1000))}
        r = _SESSION.get(EM_LIST_URL, params=p, timeout=25,
                         headers={"Referer": "https://finance.eastmoney.com/"})
        r.raise_for_status()
        js = r.json()
        items = ((js.get("data") or {}).get("list")) or []
        out = []
        for it in items:
            title = (it.get("title") or it.get("shortTitle") or "").strip()
            if not title:
                continue
            # 东财列表的摘要字段叫 summary（不是 digest）
            body = (it.get("summary") or it.get("digest") or it.get("content") or "").strip()
            out.append(dict(
                source="em_list",
                channel=it.get("mediaName") or column,
                title=title,
                content=body or None,
                published_at=_iso(it.get("showTime") or it.get("date")),
                url=it.get("uniqueUrl") or it.get("url") or it.get("newsUrl"),
            ))
        return out

    return _retry(_call, f"em_list p{page_index}", log=log)


# ============================================================
# 财联社电报（可回溯，需自算 sign）
# ============================================================
CLS_URL = "https://www.cls.cn/v1/roll/get_roll_list"


def _cls_sign(params: dict) -> str:
    return hashlib.md5(
        hashlib.sha1(urlencode(params).encode("utf-8")).hexdigest().encode("utf-8")
    ).hexdigest()


def fetch_cls_page(last_time=None, rn=20, log=print):
    def _call():
        params = {
            "app": "CailianpressWeb",
            "category": "",
            "last_time": int(last_time if last_time else time.time()),
            "os": "web",
            "refresh_type": "1",
            "rn": str(rn),
            "sv": "8.4.6",
        }
        params["sign"] = _cls_sign(params)
        r = _SESSION.get(CLS_URL, params=params, timeout=25,
                         headers={"Referer": "https://www.cls.cn/telegraph"})
        r.raise_for_status()
        items = ((r.json().get("data") or {}).get("roll_data")) or []
        out = []
        for it in items:
            title = (it.get("title") or it.get("brief") or "").strip()
            content = (it.get("content") or it.get("brief") or "").strip()
            if not title and not content:
                continue
            tid = it.get("id") or it.get("telegraph_id")
            out.append(dict(
                source="cls",
                channel=it.get("category") or it.get("level"),
                title=title or content[:40],
                content=content or None,
                published_at=_iso(it.get("ctime")),
                url=it.get("shareurl") or (f"https://www.cls.cn/detail/{tid}" if tid else None),
            ))
        return out

    return _retry(_call, f"cls last_time={last_time}", log=log)


# ============================================================
# 快照源（实时采集用，akshare 封装）
# ============================================================
def fetch_em_flash(log=print):
    def _call():
        import akshare as ak
        df = ak.stock_info_global_em()
        out = []
        for _, r in df.iterrows():
            content = str(r["摘要"]).strip()
            title = str(r["标题"]).strip() or content[:40]
            out.append(dict(source="em_flash", channel="快讯",
                            title=title,
                            content=content or None,
                            published_at=_iso(r["发布时间"]),
                            url=r.get("链接")))
        return out
    return _retry(_call, "em_flash", log=log)


def fetch_cls_snapshot(log=print):
    def _call():
        import akshare as ak
        df = ak.stock_info_global_cls(symbol="全部")
        out = []
        for _, r in df.iterrows():
            content = str(r["内容"]).strip()
            # 电报里有些条目只有正文没有标题，用正文前 40 字兜底
            title = str(r["标题"]).strip() or content[:40]
            out.append(dict(source="cls_live", channel="电报",
                            title=title,
                            content=content or None,
                            published_at=_iso(f"{r['发布日期']} {r['发布时间']}"),
                            url=None))
        return out
    return _retry(_call, "cls_snapshot", log=log)
