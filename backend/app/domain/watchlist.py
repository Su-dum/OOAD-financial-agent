# -*- coding: utf-8 -*-
"""自选股（监控列表）领域对象。

对应提案 4.4 的 `Watchlist` / `MonitoringTask`：
用户挑选一组股票持续关注，系统只对这些标的做事件检测与情报更新。

设计：`Watchlist` 是聚合根，持有若干 `WatchItem`（值对象），
提供去重添加、移除、代码列表等行为；持久化交给仓储。
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Iterable, Optional


@dataclass(frozen=True)
class WatchItem:
    code: str
    name: str = ""
    industry: str = ""
    added_at: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Watchlist:
    items: list[WatchItem] = field(default_factory=list)

    # ---------------- 查询 ----------------
    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    @property
    def codes(self) -> list[str]:
        return [i.code for i in self.items]

    def has(self, code: str) -> bool:
        c = str(code).split(".")[0]
        return any(i.code == c for i in self.items)

    def get(self, code: str) -> Optional[WatchItem]:
        c = str(code).split(".")[0]
        for i in self.items:
            if i.code == c:
                return i
        return None

    # ---------------- 行为 ----------------
    def add(self, code: str, name: str = "", industry: str = "",
            note: str = "") -> bool:
        """加入自选。已存在返回 False（幂等）。"""
        c = str(code).split(".")[0]
        if self.has(c):
            return False
        self.items.append(WatchItem(
            code=c, name=name, industry=industry, note=note,
            added_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        return True

    def remove(self, code: str) -> bool:
        c = str(code).split(".")[0]
        before = len(self.items)
        self.items = [i for i in self.items if i.code != c]
        return len(self.items) < before

    def extend(self, codes: Iterable[str], catalog=None) -> int:
        """批量加入；catalog 用于补全名称与行业。返回新增条数。"""
        added = 0
        for c in codes:
            name = industry = ""
            if catalog is not None:
                name = catalog.name_of(c)
                industry = catalog.industry_of(c)
            if self.add(c, name=name, industry=industry):
                added += 1
        return added

    def to_dict(self) -> list[dict]:
        return [i.to_dict() for i in self.items]
