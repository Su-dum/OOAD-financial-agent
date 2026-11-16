# -*- coding: utf-8 -*-
"""并发相关测试：防止「跨线程用 SQLite 连接」这类问题回归。

背景：FastAPI 的同步端点跑在线程池里，同一个请求可能落在不同线程。
早期连接没开 `check_same_thread=False`，导致生产环境随机 500：
    ProgrammingError: SQLite objects created in a thread can only be used
    in that same thread
这个 bug 在单线程的单元测试里完全看不出来，所以单独建一个测试文件。
"""
import sys
import sqlite3
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db as dbmod


@pytest.fixture()
def tmp_db(tmp_path):
    p = tmp_path / "test.db"
    con = dbmod.connect(p)
    dbmod.init_schema(con)
    yield con, p
    try:
        con.close()
    except Exception:
        pass


def test_connection_can_be_used_from_another_thread(tmp_db):
    """主线程创建连接，子线程查询——不应该抛 ProgrammingError。"""
    con, _ = tmp_db
    result = {}

    def worker():
        try:
            n = con.execute("SELECT COUNT(*) FROM news").fetchone()[0]
            result["ok"] = True
            result["count"] = n
        except Exception as e:                      # noqa: BLE001
            result["ok"] = False
            result["err"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=10)
    assert result.get("ok") is True, result.get("err")
    assert result["count"] >= 0


def test_multiple_threads_read_concurrently(tmp_db):
    """多线程并发读，全部成功。"""
    con, _ = tmp_db
    errors = []
    lock = threading.Lock()

    def reader():
        try:
            con.execute("SELECT COUNT(*) FROM news").fetchone()
        except Exception as e:                      # noqa: BLE001
            with lock:
                errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert errors == [], errors


def test_write_from_other_thread(tmp_db):
    """跨线程写（事件表）也要成功。"""
    con, _ = tmp_db
    result = {}

    def writer():
        try:
            con.execute(
                "INSERT INTO event(code,name,event_type,trade_date,detected_at,"
                "severity,value,threshold,detail,rule_name) "
                "VALUES('600519','贵州茅台','price_drop','2026-10-20','now',"
                "'high',-0.08,-0.05,'跌 8%','test')")
            con.commit()
            result["ok"] = True
        except Exception as e:                      # noqa: BLE001
            result["ok"] = False
            result["err"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=writer)
    t.start()
    t.join(timeout=10)
    assert result.get("ok") is True, result.get("err")
    assert con.execute("SELECT COUNT(*) FROM event").fetchone()[0] == 1


def test_threadsafe_flags_are_set(tmp_db):
    """显式断言连接配置，避免有人把 check_same_thread 改回去。"""
    con, _ = tmp_db
    # sqlite3 没有公开属性，只能通过跨线程调用间接验证（上面几个用例已覆盖）；
    # 这里验证 timeout 生效（写入 busy_timeout 后能读到）
    assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
