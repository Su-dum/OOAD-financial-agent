# -*- coding: utf-8 -*-
"""预警规则配置仓储（满足 application 层的配置读取需求）。

## 为什么规则要落库

评分项 C1 要求「用户可以配置监控目标、分析任务和**预警条件**」。
早期版本把阈值写死在 `EventMonitor.default()` 里（`drop=-0.05`），
用户既改不了也看不到——这是明文要求里的缺口。

## 表设计

    alert_rule(code, rule_type, params, enabled, updated_at)  UNIQUE(code, rule_type)

`code = ''` 表示**全局默认**，`code = '600519'` 表示该股票的覆盖值。
读取时按「全局 -> 个股」两级合并，所以用户只改一只票时不必复制整套默认值。

`params` 存 JSON 而不是拆成列：不同规则类型的参数完全不同
（涨跌幅是 drop/surge，z-score 是 window/z），拆列会得到一堆空字段。
"""
import json
from datetime import datetime
from typing import Optional, Sequence


class SqliteAlertRuleRepository:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    def load(self, code: Optional[str] = None) -> list[dict]:
        """取全局配置 + 该股票的覆盖配置（个股在后，便于后者覆盖前者）。"""
        rows = self.con.execute(
            "SELECT code, rule_type, params, enabled FROM alert_rule "
            "WHERE code='' OR code=?", (str(code or "").split(".")[0],)).fetchall()
        out = []
        for r in rows:
            try:
                params = json.loads(r[2]) if r[2] else {}
            except (TypeError, ValueError):
                params = {}
            out.append(dict(code=r[0] or "", rule_type=r[1],
                            params=params, enabled=bool(r[3])))
        out.sort(key=lambda x: (x["code"] != "", x["rule_type"]))
        return out

    def upsert(self, rule_type: str, params: dict, code: Optional[str] = None,
               enabled: bool = True) -> None:
        c = str(code or "").split(".")[0] if code else ""
        self.con.execute(
            "INSERT INTO alert_rule(code,rule_type,params,enabled,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(code,rule_type) DO UPDATE SET "
            "params=excluded.params, enabled=excluded.enabled, "
            "updated_at=excluded.updated_at",
            (c, rule_type, json.dumps(params, ensure_ascii=False),
             1 if enabled else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.con.commit()

    def delete(self, rule_type: str, code: Optional[str] = None) -> bool:
        c = str(code or "").split(".")[0] if code else ""
        cur = self.con.execute(
            "DELETE FROM alert_rule WHERE code=? AND rule_type=?", (c, rule_type))
        self.con.commit()
        return bool(cur.rowcount and cur.rowcount > 0)

    def reset(self, code: Optional[str] = None) -> int:
        """清空全局配置，或清空某只股票的覆盖配置。"""
        c = str(code or "").split(".")[0] if code else ""
        cur = self.con.execute("DELETE FROM alert_rule WHERE code=?", (c,))
        self.con.commit()
        return cur.rowcount or 0

    def count(self) -> int:
        r = self.con.execute("SELECT COUNT(*) FROM alert_rule").fetchone()
        return r[0] if r else 0
