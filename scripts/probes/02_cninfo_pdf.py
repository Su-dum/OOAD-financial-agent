# -*- coding: utf-8 -*-
"""验证：巨潮资讯公告 PDF 能否自动定位 -> 下载 -> 抽取正文"""
import io, sys, re, time, json
from urllib.parse import urlparse, parse_qs

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests
import akshare as ak

CODE = "600519"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
import os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUT, exist_ok=True)
LOG = []


def log(s=""):
    print(s)
    LOG.append(str(s))


log("=" * 72)
log("巨潮公告 PDF 可获取性验证")
log("=" * 72)

# ---------- 1. 拉公告列表 ----------
log("\n[1] 拉取公告列表 ...")
t0 = time.time()
df = ak.stock_zh_a_disclosure_report_cninfo(
    symbol=CODE, market="沪深京", start_date="20250101", end_date="20261231"
)
log(f"    返回 {len(df)} 条，耗时 {time.time()-t0:.1f}s")
log(f"    列: {list(df.columns)}")
log(f"    首条链接: {df.iloc[0]['公告链接']}")
log(f"    首条标题: {df.iloc[0]['公告标题']}")

# ---------- 2. 解析 PDF 地址 ----------
log("\n[2] 从详情链接解析 announcementId / orgId / 日期 ...")
rows = []
for _, r in df.head(6).iterrows():
    link = str(r["公告链接"])
    q = parse_qs(urlparse(link).query)
    ann_id = (q.get("announcementId") or [""])[0]
    org_id = (q.get("orgId") or [""])[0]
    ann_time = (q.get("announcementTime") or [""])[0]
    rows.append(dict(title=r["公告标题"], link=link, ann_id=ann_id,
                     org_id=org_id, time=ann_time))
    log(f"    {ann_time} | id={ann_id} | org={org_id} | {str(r['公告标题'])[:40]}")

# ---------- 3. 定位真实 PDF (两种策略) ----------
log("\n[3] 定位 PDF 直链 ...")
sess = requests.Session()
sess.headers.update({"User-Agent": UA,
                     "Referer": "http://www.cninfo.com.cn/new/disclosure/stock"})

CNINFO_QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"


def pdf_by_api(stock, org_id):
    """官方查询接口，返回 adjunctUrl"""
    payload = {
        "pageNum": 1, "pageSize": 30, "column": "szse", "tabName": "fulltext",
        "plate": "", "stock": f"{stock},{org_id}", "searchkey": "", "secid": "",
        "category": "", "trade": "", "seDate": "2025-01-01~2026-12-31",
        "sortName": "", "sortType": "", "isHLtitle": "true",
    }
    r = sess.post(CNINFO_QUERY, data=payload, timeout=20)
    r.raise_for_status()
    js = r.json()
    return js.get("announcements") or []


def pdf_by_static(ann_id, ann_time):
    """猜测静态地址 finalpage/{date}/{id}.PDF"""
    d = str(ann_time).strip()
    if len(d) == 13:  # 毫秒时间戳
        import datetime
        d = datetime.datetime.fromtimestamp(int(d) / 1000).strftime("%Y-%m-%d")
    cand = f"http://static.cninfo.com.cn/finalpage/{d}/{ann_id}.PDF"
    return cand


api_items = []
try:
    t0 = time.time()
    api_items = pdf_by_api(CODE, rows[0]["org_id"])
    log(f"    [策略A] 官方查询接口 OK：{len(api_items)} 条，耗时 {time.time()-t0:.1f}s")
    if api_items:
        log(f"    [策略A] 首条字段: {json.dumps(api_items[0], ensure_ascii=False)[:400]}")
except Exception as e:
    log(f"    [策略A] 官方查询接口 FAIL: {type(e).__name__}: {str(e)[:150]}")

# ---------- 4. 下载 ----------
log("\n[4] 下载 PDF ...")
downloaded = []
targets = []
if api_items:
    for it in api_items[:4]:
        adj = it.get("adjunctUrl") or ""
        if not adj:
            continue
        url = adj if adj.startswith("http") else "http://static.cninfo.com.cn/" + adj.lstrip("/")
        targets.append((it.get("announcementTitle", "")[:40], url))
else:
    for r_ in rows[:4]:
        targets.append((r_["title"], pdf_by_static(r_["ann_id"], r_["time"])))

for i, (title, url) in enumerate(targets):
    try:
        t0 = time.time()
        resp = sess.get(url, timeout=30)
        ct = resp.headers.get("Content-Type", "")
        ok = resp.status_code == 200 and resp.content[:4] == b"%PDF"
        log(f"    [{i}] {resp.status_code} {len(resp.content)/1024:.0f}KB "
            f"{time.time()-t0:.1f}s PDF={resp.content[:4] == b'%PDF'} ct={ct[:40]}")
        log(f"         {url}")
        if ok:
            path = f"{OUT}\\notice_{i}.pdf"
            with open(path, "wb") as f:
                f.write(resp.content)
            downloaded.append((path, title))
    except Exception as e:
        log(f"    [{i}] FAIL {type(e).__name__}: {str(e)[:120]}")

# ---------- 5. 抽取正文 ----------
log("\n[5] 抽取 PDF 正文 ...")
for path, title in downloaded:
    # 5a. PyMuPDF
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        t0 = time.time()
        doc = fitz.open(path)
        pages = doc.page_count
        txt = "\n".join(p.get_text() for p in doc)
        cjk = len(re.findall(r"[\u4e00-\u9fff]", txt))
        log(f"    [pymupdf] pages={pages} chars={len(txt)} CJK={cjk} "
            f"{time.time()-t0:.2f}s  <- {title[:30]}")
        if txt.strip():
            preview = re.sub(r"\s+", " ", txt.strip())[:220]
            log(f"              预览: {preview}")
        doc.close()
    except Exception as e:
        log(f"    [pymupdf] FAIL {type(e).__name__}: {str(e)[:120]}")

    # 5b. pypdf
    try:
        from pypdf import PdfReader
        t0 = time.time()
        rd = PdfReader(path)
        txt2 = "".join((p.extract_text() or "") for p in rd.pages)
        cjk2 = len(re.findall(r"[\u4e00-\u9fff]", txt2))
        log(f"    [pypdf]   pages={len(rd.pages)} chars={len(txt2)} CJK={cjk2} "
            f"{time.time()-t0:.2f}s")
    except Exception as e:
        log(f"    [pypdf]   FAIL {type(e).__name__}: {str(e)[:120]}")

log("\n" + "=" * 72)
log("完成")
with open(f"{OUT}\\02_cninfo_pdf.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(LOG))
