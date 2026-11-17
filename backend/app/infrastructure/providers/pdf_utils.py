# -*- coding: utf-8 -*-
"""公告 PDF 下载与正文抽取（两个公告 Provider 共用）。

巨潮的公告正文是 PDF，链接形如：

    详情：http://www.cninfo.com.cn/new/disclosure/detail?
          stockCode=600519&announcementId=1225475868&orgId=...&announcementTime=2026-08-15
    直链：http://static.cninfo.com.cn/finalpage/2026-08-15/1225475868.PDF

实测一份 110 页的半年报 0.15s 抽出 5.8 万中文字，文本型无需 OCR。
"""
from typing import Optional
from urllib.parse import parse_qs, urlparse

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def pdf_url_from_detail(detail_url: str) -> Optional[str]:
    """从巨潮详情链接解析出 static 直链；解析不出来返回 None。"""
    if not detail_url:
        return None
    q = parse_qs(urlparse(detail_url).query)
    ann_id = (q.get("announcementId") or [""])[0]
    ann_time = (q.get("announcementTime") or [""])[0][:10]
    if not ann_id or not ann_time:
        return None
    return f"http://static.cninfo.com.cn/finalpage/{ann_time}/{ann_id}.PDF"


def resolve_pdf_url(url: str) -> Optional[str]:
    """详情链接 / 直链都接受，统一成可下载的 PDF 直链。"""
    if not url:
        return None
    if url.lower().endswith(".pdf"):
        return url
    return pdf_url_from_detail(url)


def extract_pdf_text(content: bytes, max_pages: Optional[int] = None) -> str:
    """从 PDF 字节流抽正文（PyMuPDF）。"""
    try:
        import pymupdf
    except ImportError:                                    # pragma: no cover
        import fitz as pymupdf
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        pages = doc.page_count if max_pages is None else min(max_pages, doc.page_count)
        return "\n".join(doc[i].get_text() for i in range(pages))


def download_pdf_text(session, url: str, timeout: int = 30,
                      max_pages: Optional[int] = None, attempts: int = 3,
                      log=print) -> str:
    """下载 + 抽正文。失败重试后返回空字符串（不抛异常，证据缺失好过整条链崩）。"""
    import time

    pdf_url = resolve_pdf_url(url)
    if not pdf_url:
        return ""
    for attempt in range(attempts):
        try:
            r = session.get(pdf_url, timeout=timeout)
            r.raise_for_status()
            if r.content[:4] != b"%PDF":
                raise ValueError("返回的不是 PDF")
            return extract_pdf_text(r.content, max_pages=max_pages)
        except Exception as ex:                            # noqa: BLE001
            wait = 2 * (attempt + 1)
            if log:
                log(f"  [pdf] 第 {attempt+1} 次失败: {type(ex).__name__} -> {wait}s")
            if attempt < attempts - 1:
                time.sleep(wait)
    return ""


def default_session():
    """带 UA / Referer 的 requests.Session（巨潮对裸请求会拒）。"""
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Referer": "http://www.cninfo.com.cn/"})
    return s
