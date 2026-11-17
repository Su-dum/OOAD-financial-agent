# -*- coding: utf-8 -*-
"""巨潮资讯公告适配器（满足 domain.ports.NoticeProvider）。

巨潮是交易所指定披露平台，公告权威性最高。链路已在探针 `02_cninfo_pdf.py` 验证：

    列表（akshare 封装，带 orgId） -> 从详情链接解析 announcementId + 日期
      -> 拼 static.cninfo.com.cn 直链下载 PDF -> PyMuPDF 抽正文

它负责**取正文**；分类所需的「公告类型」字段巨潮不给（实测 `announcementTypeName`
为空，只有数字编码），所以分类走标题关键词（`domain/notices.py`）。
"""
import re
from typing import Optional

from .pdf_utils import (default_session, download_pdf_text, extract_pdf_text,
                        pdf_url_from_detail)
from .akshare_compat import call as akcall


class CninfoNoticeProvider:
    name = "cninfo"

    def __init__(self, log=print, timeout: int = 30):
        self.log = log
        self.timeout = timeout
        self._session = default_session()

    # ---------------- 列表 ----------------
    def list_notices(self, code: str, start: str, end: str,
                     limit: int = 30) -> list[dict]:
        c = str(code).split(".")[0]
        s = re.sub(r"[^0-9]", "", start)[:8]
        e = re.sub(r"[^0-9]", "", end)[:8]
        try:
            df = akcall("stock_zh_a_disclosure_report_cninfo",
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
                notice_type="",                       # 巨潮不提供可读类型
                published_at=str(r.get("公告时间", ""))[:10],
                url=str(r.get("公告链接", "")).strip(),
                source=self.name))
        return out

    # ---------------- 正文 ----------------
    @staticmethod
    def pdf_url_from_detail(detail_url: str) -> Optional[str]:
        """从详情链接解析出 static 直链（兼容旧调用）。"""
        return pdf_url_from_detail(detail_url)

    def fetch_text(self, url: str, max_pages: Optional[int] = None) -> str:
        """下载公告 PDF 并抽取正文。url 可以是详情链接或 static 直链。"""
        return download_pdf_text(self._session, url, timeout=self.timeout,
                                 max_pages=max_pages, log=self.log)

    @staticmethod
    def _extract(content: bytes, max_pages: Optional[int] = None) -> str:
        return extract_pdf_text(content, max_pages=max_pages)
