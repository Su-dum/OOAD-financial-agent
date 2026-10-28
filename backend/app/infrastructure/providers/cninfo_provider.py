# -*- coding: utf-8 -*-
"""巨潮资讯公告适配器（满足 domain.ports.NoticeProvider）。

巨潮是交易所指定披露平台，公告权威性最高。链路已在探针 `02_cninfo_pdf.py` 验证：

    列表（akshare 封装，带 orgId） -> 从详情链接解析 announcementId + 日期
      -> 拼 static.cninfo.com.cn 直链下载 PDF -> PyMuPDF 抽正文

实测一份 110 页的半年报 0.15s 抽出 5.8 万中文字，文本型无需 OCR。
"""
import re
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_DETAIL_KEYS = ("announcementId", "announcementTime")


class CninfoNoticeProvider:
    name = "cninfo"

    def __init__(self, log=print, timeout: int = 30):
        self.log = log
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _UA,
                                      "Referer": "http://www.cninfo.com.cn/"})

    # ---------------- 列表 ----------------
    def list_notices(self, code: str, start: str, end: str,
                     limit: int = 30) -> list[dict]:
        import akshare as ak
        c = str(code).split(".")[0]
        s = re.sub(r"[^0-9]", "", start)[:8]
        e = re.sub(r"[^0-9]", "", end)[:8]
        try:
            df = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=c, market="沪深京", start_date=s, end_date=e)
        except Exception as ex:
            if self.log:
                self.log(f"  [cninfo] 列表失败: {type(ex).__name__} {str(ex)[:60]}")
            return []
        out = []
        for _, r in df.head(limit).iterrows():
            out.append(dict(
                code=c,
                name=str(r.get("简称", "")).strip(),
                title=str(r.get("公告标题", "")).strip(),
                published_at=str(r.get("公告时间", ""))[:10],
                url=str(r.get("公告链接", "")).strip(),
                source=self.name))
        return out

    # ---------------- 正文 ----------------
    @staticmethod
    def pdf_url_from_detail(detail_url: str) -> Optional[str]:
        """从详情链接解析出 static 直链。

        详情：http://www.cninfo.com.cn/new/disclosure/detail?
              stockCode=600519&announcementId=1225475868&orgId=gssh0600519&
              announcementTime=2026-08-15 00:00:00
        PDF： http://static.cninfo.com.cn/finalpage/2026-08-15/1225475868.PDF
        """
        if not detail_url:
            return None
        q = parse_qs(urlparse(detail_url).query)
        ann_id = (q.get("announcementId") or [""])[0]
        ann_time = (q.get("announcementTime") or [""])[0][:10]
        if not ann_id or not ann_time:
            return None
        return f"http://static.cninfo.com.cn/finalpage/{ann_time}/{ann_id}.PDF"

    def fetch_text(self, url: str, max_pages: Optional[int] = None) -> str:
        """下载公告 PDF 并抽取正文。url 可以是详情链接或 static 直链。"""
        pdf_url = url if url.lower().endswith(".pdf") else self.pdf_url_from_detail(url)
        if not pdf_url:
            return ""
        for attempt in range(3):
            try:
                r = self._session.get(pdf_url, timeout=self.timeout)
                r.raise_for_status()
                if not r.content[:4] == b"%PDF":
                    raise ValueError("返回的不是 PDF")
                return self._extract(r.content, max_pages=max_pages)
            except Exception as ex:
                wait = 2 * (attempt + 1)
                if self.log:
                    self.log(f"  [cninfo] PDF 第 {attempt+1} 次失败: "
                             f"{type(ex).__name__} -> {wait}s")
                if attempt < 2:
                    time.sleep(wait)
        return ""

    @staticmethod
    def _extract(content: bytes, max_pages: Optional[int] = None) -> str:
        try:
            import pymupdf
        except ImportError:                                    # pragma: no cover
            import fitz as pymupdf
        with pymupdf.open(stream=content, filetype="pdf") as doc:
            pages = doc.page_count if max_pages is None else min(max_pages, doc.page_count)
            return "\n".join(doc[i].get_text() for i in range(pages))
