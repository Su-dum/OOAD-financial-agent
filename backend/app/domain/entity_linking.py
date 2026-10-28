# -*- coding: utf-8 -*-
"""实体链接：把新闻正文里的「股票代码 / 公司简称」识别出来，建立 新闻 <-> 股票 关系。

两种通道：
  1. 代码匹配：正文里出现 6 位 A 股代码（如 600519 / 600519.SH），且该代码在股票表里 -> 置信度 1.0
  2. 名称匹配：公司简称（>=3 字）出现在正文 -> 置信度 0.9

性能：不遍历 4000 个股票名去 in 文本（那太慢），而是对每条文本生成 3~8 字的 n-gram，
再查「名称 -> 股票」字典。一条 200 字新闻约 1200 次哈希查找，很快。
"""
import re
import csv
from pathlib import Path

_CODE_RE = re.compile(r"(?<!\d)((?:60|68|00|30|43|83|87|92)\d{4})(?!\d)")
_SUFFIX_RE = re.compile(r"\.(?:SH|SZ|BJ)$", re.I)

# 简称里常见的前缀噪声，索引时额外生成一个去前缀的别名
_PREFIXES = ("*ST", "ST", "N", "C", "U", "W", "XD", "XR", "DR", "退")

MIN_NAME_LEN = 3
MAX_NAME_LEN = 8

# 既是股票简称、又是常见行业/概念词的名称，单独降权。
# 例：「机器人」是 300024 的简称，但新闻里几乎都在说「人形机器人赛道」。
AMBIGUOUS_NAMES = {
    "机器人", "东方", "中国", "数据", "智能", "网络", "环保",
    "电力", "水务", "燃气", "传媒", "化工", "钢铁", "煤炭",
    "有色", "建材", "家电", "汽车", "银行", "证券", "保险",
}


def _conf_by_len(name: str) -> float:
    """名称长度分档：4 字以上较可靠，3 字容易命中通用词，2 字基本不可用。"""
    n = len(name)
    if name in AMBIGUOUS_NAMES:
        return 0.40
    if n >= 4:
        return 0.90
    if n == 3:
        return 0.70
    return 0.50


class StockIndex:
    def __init__(self, names: dict, codes: set):
        self.names = names          # name -> [(code, name, match_type, confidence)]
        self.codes = codes
        self.lens = sorted({len(n) for n in names}, reverse=True)

    def __len__(self):
        return len(self.codes)


def _strip_prefix(name: str) -> str:
    for p in _PREFIXES:
        if name.startswith(p) and len(name) - len(p) >= MIN_NAME_LEN:
            return name[len(p):]
    return name


def build_index(csv_path) -> StockIndex:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"缺少股票映射表：{path}（先跑 scripts/build_industry_map.py）")

    names, codes = {}, set()
    skipped_short = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            code = (r.get("code") or "").strip()
            name = (r.get("name") or "").strip()
            if not code or not name:
                continue
            codes.add(code)
            candidates = {name}
            alt = _strip_prefix(name)
            if alt != name:
                candidates.add(alt)
            for c in candidates:
                if len(c) < MIN_NAME_LEN:
                    skipped_short += 1
                    continue
                conf = _conf_by_len(c)
                if c != name:            # 去掉 ST/N 等前缀后的别名，可靠性略降
                    conf = max(0.40, conf - 0.05)
                names.setdefault(c, []).append((code, name, "name", conf))
    print(f"[link] 索引：{len(codes)} 只股票，{len(names)} 个名称别名"
          + (f"（跳过 {skipped_short} 个过短名称）" if skipped_short else ""))
    return StockIndex(names, codes)


def extract(text: str, idx: StockIndex) -> dict:
    """返回 {code: (match_type, confidence)}"""
    hits = {}
    if not text:
        return hits
    t = _SUFFIX_RE.sub("", text)

    # 1) 代码
    for m in _CODE_RE.finditer(t):
        code = m.group(1)
        if code in idx.codes:
            hits[code] = ("code", 1.0)

    # 2) 名称 n-gram（长名优先覆盖）
    n = len(t)
    taken = []
    for L in idx.lens:
        if L > n:
            continue
        for i in range(n - L + 1):
            gram = t[i:i + L]
            lst = idx.names.get(gram)
            if not lst:
                continue
            # 被更长的匹配覆盖则跳过
            if any(a <= i and i + L <= b for a, b in taken):
                continue
            taken.append((i, i + L))
            for code, real_name, mtype, conf in lst:
                if code not in hits or hits[code][1] < conf:
                    hits[code] = (mtype, conf)
    return hits


def link_texts(texts, idx: StockIndex):
    """批量：返回 [ {code: (type, conf)} , ... ]"""
    return [extract(t, idx) for t in texts]
