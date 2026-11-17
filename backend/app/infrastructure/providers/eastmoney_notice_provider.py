# -*- coding: utf-8 -*-
"""东财公告适配器（满足 domain.ports.NoticeProvider）。

为什么不用巨潮就够了？因为**分类需要「公告类型」字段**：

  东财 `stock_individual_notice_report` 一次返回一只票的全部历史公告（实测
  600519 有 1074 条、87 种公告类型），带 `公告类型` 文本。巨潮的
  `announcementTypeName` 实测为空，只能靠标题猜。

两者分工：
    东财  取「列表 + 类型」-> 喂给 B2 的事件分类
    巨潮  取「PDF 正文」  -> 喂给 B3 的证据引用

实测（探针 `07_notice_types.py`）：一次请求 3 秒内拿回 1074 条，
类型分布里 `股票`(229) / `其他`(110) 是噪音桶，真正的信号在标题里。
"""
import re
from typing import Optional

from .pdf_utils import default_session, download_pdf_text
from .akshare_compat import call as akcall

# akshare 不同版本的列名有波动，做一层别名归一化，避免升级就崩
_ALIAS = {
    "name": ("名称", "简称", "股票简称", "name"),
    "title": ("公告标题", "标题", "公告名称", "title"),
    "notice_type": ("公告类型", "类型", "notice_type"),
    "published_at": ("公告日期", "日期", "公告时间", "published_at", "时间"),
    "url": ("网址", "公告链接", "链接", "url"),
}


def _pick(row, keys, default=""):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


class EastmoneyNoticeProvider:
    name = "eastmoney"

    def __init__(self, log=print, timeout: int = 30):
        self.log = log
        self.timeout = timeout
        self._session = default_session()

    # ---------------- 列表 ----------------
    def list_notices(self, code: str, start: str, end: str,
                     limit: int = 500) -> list[dict]:
        c = str(code).split(".")[0]
        s = re.sub(r"[^0-9]", "", start)[:8]
        e = re.sub(r"[^0-9]", "", end)[:8]
        df = self._fetch(c, s, e)
        if df is None:
            return []
        out = []
        for rec in df.to_dict("records"):
            title = str(_pick(rec, _ALIAS["title"]) or "").strip()
            day = str(_pick(rec, _ALIAS["published_at"]) or "")[:10].replace("/", "-")
            digits = re.sub(r"[^0-9]", "", day)
            if not title or len(digits) < 8:
                continue
            if s and digits < s:
                continue
            if e and digits > e:
                continue
            out.append(dict(
                code=c,
                name=str(_pick(rec, _ALIAS["name"]) or "").strip(),
                title=title,
                notice_type=str(_pick(rec, _ALIAS["notice_type"]) or "").strip(),
                published_at=f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}",
                url=str(_pick(rec, _ALIAS["url"]) or "").strip() or None,
                source=self.name))
            if len(out) >= limit:
                break
        out.sort(key=lambda x: x["published_at"], reverse=True)
        return out

    def _fetch(self, code: str, start: str = "", end: str = ""):
        """兼容 akshare 的参数名差异：新版 `symbol`+日期区间，旧版 `security`。

        新版接口支持 `start_date/end_date`，带上它能少拉几千行；
        旧版不认这两个参数，退回到「只传 security」。
        """
        attempts = [dict(symbol=code, start_date=start, end_date=end),
                    dict(symbol=code),
                    dict(security=code)]
        for kwargs in attempts:
            try:
                df = akcall("stock_individual_notice_report", **kwargs)
                if df is not None and len(df) > 0:
                    return df
            except Exception as ex:                        # noqa: BLE001
                if self.log:
                    self.log(f"  [notice] 东财列表失败({list(kwargs)}): "
                             f"{type(ex).__name__} {str(ex)[:60]}")
        return None

    # ---------------- 正文（东财公告链接指向巨潮 PDF）----------------
    def fetch_text(self, url: str, max_pages: Optional[int] = None) -> str:
        return download_pdf_text(self._session, url, timeout=self.timeout,
                                 max_pages=max_pages, log=self.log)
