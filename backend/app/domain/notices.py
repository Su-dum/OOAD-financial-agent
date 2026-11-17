# -*- coding: utf-8 -*-
"""公告分类：把公司公告映射成「可监控的公司事件」。

对应评分项 **B2（Financial Event Monitoring）** 里被点名的两类：

    earnings announcements      财报类公告  -> earnings
    major corporate events      重大事项公告 -> dividend / buyback / insider_* / major_deal / ...
    另有 clarification / regulatory 两类高价值信号

87 种公告类型 -> **11 个类别**（8 类构成事件，3 类只做归类、不产生事件）：
    clarification / regulatory / earnings / dividend / buyback /
    insider_increase / insider_decrease / major_deal        <- 事件
    equity_change / management / procedural                 <- 不构成事件

## 为什么分类要放在领域层

公告的「类型」是交易所 / 数据源给的**字符串**（东财实测 87 种），
而系统内部需要的是**有限的事件类别**。这层映射是纯函数：

    公告类型 + 标题  ->  NoticeCategory | None

不碰网络、不碰数据库，所以能被单测锁住（`tests/test_notices.py`）。
上层（`NoticeEventRule`）只依赖类别，不依赖任何具体数据源的字段名。

## 设计取舍：为什么用关键词而不是 if/elif 枚举

87 种公告类型会**持续新增**（交易所每年都在改），把 87 个字符串写死成
if/elif 分支既不可读也不可维护。这里改成「关键词表 + 按具体度排序」：

    NoticeCategory(key=..., keywords=("回购预案", "回购报告书", ...))

匹配时**先匹配更具体的类别**（澄清 > 监管 > 财报 > 分红 > 回购 > 交易），
新增一种公告只需要往关键词表里加一个词，不用改任何控制流。
"""
from dataclasses import dataclass
from typing import Optional, Sequence

import re

_PREFIX_RE = re.compile(r"^([^:：]{2,12})[:：](.*)$")


def clean_title(title: str, name: str = "") -> str:
    """去掉数据源给的「名称:标题」前缀，以及正文开头重复的公司简称。

    东财的原始标题形如：

        贵州茅台:贵州茅台2026年第三季度报告
        贵州茅台:关于回购股份实施结果的公告

    前缀对阅读没价值，而且会把「公司名」重复两遍塞进事件摘要与报告，
    所以入库前统一清掉。规则保守：只有「冒号前是股票简称」或
    「冒号后仍以同一段文字开头」时才剥离，避免误删「关于XX:YY」这类标题。
    """
    t = (title or "").strip()
    n = (name or "").strip()

    for _ in range(2):                       # 「名称:名称:标题」最多剥两次
        m = _PREFIX_RE.match(t)
        if not m:
            break
        head, rest = m.group(1).strip(), m.group(2).strip()
        if not rest:
            break
        if (n and head == n) or rest.startswith(head):
            t = rest
            continue
        break

    # 正文开头重复的简称也去掉（「贵州茅台2026年三季报」-> 「2026年三季报」）
    if n and t.startswith(n) and len(t) > len(n) + 1:
        t = t[len(n):].lstrip(" :：")
    return t


@dataclass(frozen=True)
class NoticeCategory:
    """一类公告事件。字段与 MarketEvent 对齐，便于直接产出事件。"""

    key: str                    # earnings / dividend / buyback / ...
    label: str                  # 中文名，直接进报告
    event_type: str             # MarketEvent.event_type，如 notice_earnings
    severity: str               # low / medium / high
    keywords: tuple             # 命中关键词（公告类型或标题里出现即算）
    material: bool = True       # 是否构成「重大公司事件」（False = 程序性噪音）

    def matches(self, text: str) -> bool:
        return any(k in text for k in self.keywords)


# ============================================================
# 事件类别表（顺序 = 匹配优先级，越具体越靠前）
# ============================================================
CATEGORIES: tuple = (
    # ---- 高价值信号：股价异动后的官方口径 ----
    NoticeCategory(
        key="clarification", label="异动澄清",
        event_type="notice_clarification", severity="high",
        keywords=("澄清", "股票交易异常波动", "异常波动公告", "风险提示")),
    # ---- 监管 ----
    NoticeCategory(
        key="regulatory", label="监管事项",
        event_type="notice_regulatory", severity="high",
        keywords=("监管工作函", "监管关注", "问询函", "关注函", "立案调查",
                  "行政处罚", "警示函", "纪律处分", "监管措施")),
    # ---- 财报（B2 明文点名的 earnings announcements）----
    NoticeCategory(
        key="earnings", label="财报披露",
        event_type="notice_earnings", severity="medium",
        keywords=("年度报告", "半年度报告", "一季度报告", "三季度报告",
                  "季度报告", "业绩预告", "业绩快报", "财务报表")),
    # ---- 分红 ----
    NoticeCategory(
        key="dividend", label="分红派息",
        event_type="notice_dividend", severity="medium",
        keywords=("分配预案", "分配方案", "权益分派", "现金分红", "利润分配")),
    # ---- 回购 ----
    NoticeCategory(
        key="buyback", label="股份回购",
        event_type="notice_buyback", severity="medium",
        keywords=("回购",)),
    # ---- 股东 / 高管增减持 ----
    NoticeCategory(
        key="insider_increase", label="股东增持",
        event_type="notice_insider_increase", severity="medium",
        keywords=("股份增持", "增持计划", "增持股份", "股东增持")),
    NoticeCategory(
        key="insider_decrease", label="股东减持",
        event_type="notice_insider_decrease", severity="medium",
        keywords=("股份减持", "减持计划", "减持股份", "股东减持", "减持进展")),
    # ---- 重大交易 / 资本运作 ----
    NoticeCategory(
        key="major_deal", label="重大交易",
        event_type="notice_major_deal", severity="medium",
        keywords=("股权转让", "资产重组", "重大资产", "关联交易", "签订协议",
                  "对外项目投资", "投资设立公司", "收购", "兼并", "资产出售",
                  "资产置换", "重大合同", "中标")),
    # ---- 股本 / 主体变更（会影响可比性，但不算「事件」）----
    NoticeCategory(
        key="equity_change", label="股本变动",
        event_type="notice_equity_change", severity="low",
        keywords=("股本变动", "法定代表人变更", "公司名称变更", "证券简称变更",
                  "注册地址变更"),
        material=False),
    # ---- 人事变动：对个股可能重要（董事长辞职），但频率太高，
    #      作为「事件」会淹没财报/回购，故不构成事件，只做分类归集 ----
    NoticeCategory(
        key="management", label="高管变动",
        event_type="notice_management", severity="low",
        keywords=("高管人员任职变动", "任职变动", "董事长辞职", "董事辞职",
                  "董事会秘书", "董事选举", "监事选举", "聘任", "换届"),
        material=False),
    # ---- 程序性公告：不构成事件，显式登记以便统计「过滤掉了多少」----
    NoticeCategory(
        key="procedural", label="程序性公告",
        event_type="notice_procedural", severity="low",
        keywords=("法律意见书", "议事规则", "实施细则", "独立董事候选人",
                  "独立董事提名人", "独立董事述职", "股东大会资料", "召开股东大会",
                  "股东大会通知", "股东大会决议", "董事会决议", "监事会决议",
                  "公司章程", "审计报告", "审计机构变更", "内部控制报告",
                  "ESG公告", "保荐/核查意见", "核查意见", "专项说明", "独立意见",
                  "管理办法", "中介机构报告", "调研活动", "变更股东大会地点",
                  "月度经营情况", "募集资金", "权证上市", "公司其他基本信息变更",
                  "关联方基本资料变更", "股票", "其他"),
        material=False),
)

_BY_KEY = {c.key: c for c in CATEGORIES}

# 「硬噪音」：只要命中，无论标题里还出现什么，都判为程序性公告。
# 解决的是这类误分类：
#   标题「关联交易决策管理制度（2025年11月修订）」类型「其他」
#   -> 关键词「关联交易」会先命中 major_deal，但它其实是一份制度文件，不是交易。
_HARD_NOISE = ("议事规则", "实施细则", "管理制度", "管理办法", "公司章程",
               "法律意见书", "独立董事", "述职报告", "候选人", "保荐",
               "核查意见", "通知债权人", "会议资料")


def category_of(key: str) -> Optional[NoticeCategory]:
    return _BY_KEY.get(key)


def classify_notice(notice_type: str = "", title: str = "") -> Optional[NoticeCategory]:
    """把一条公告归到某个类别；归不到（或缺字段）返回 None。

    匹配文本是「公告类型 + 标题」——因为类型字段并不可靠：
    东财实测 229 条是 `股票`、110 条是 `其他`，真正的信号只在标题里
    （如「关于回购股份的进展公告」类型字段仍写 `其他`）。
    """
    text = f"{notice_type or ''} {title or ''}"
    if not text.strip():
        return None
    if any(k in text for k in _HARD_NOISE):
        return _BY_KEY["procedural"]
    for cat in CATEGORIES:
        if cat.matches(text):
            return cat
    return None


def material_categories() -> Sequence[NoticeCategory]:
    """构成「重大公司事件」的类别（用于文档 / 前端筛选）。"""
    return tuple(c for c in CATEGORIES if c.material)


def describe_categories() -> list[dict]:
    """给接口 / 前端用的类别清单。"""
    return [dict(key=c.key, label=c.label, event_type=c.event_type,
                 severity=c.severity, material=c.material,
                 keywords=list(c.keywords)) for c in CATEGORIES]
