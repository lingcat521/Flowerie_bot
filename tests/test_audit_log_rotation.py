
"""审计日志轮转（fix.txt ②）：AUDIT_LOG_MAX_MB=0 关闭（默认保持历史行为），>0 才轮转。

覆盖：0=不轮转 / 小阈值触发 / 多次轮转只留两份归档 / 内容连续性与行数守恒 /
并发写入不产生半行 / 轮转失败时记忆写入仍成功。
"""
import os
import tempfile
import threading
import unittest
from unittest import mock

from src.services.memory_manager import MemoryManager


def _lines(*paths):
    total = 0
    for path in paths:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                total += len(f.readlines())
    return total


class TestAuditLogRotation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "memory.db")
        self.log = os.path.join(self.tmp.name, "audit.log")
        self.mm = None

    def tearDown(self):
        if self.mm is not None:
            self.mm.close()
        self.tmp.cleanup()

    def _mm(self, max_mb):
        self.mm = MemoryManager(self.db, audit_log_path=self.log, audit_max_mb=max_mb)
        return self.mm

    # ---------- 1) 0 = 不轮转（默认行为） ----------
    def test_zero_disables_rotation(self):
        mm = self._mm(0)
        for _ in range(200):
            mm._audit("WRITE", 1, 10, "x" * 60)
        self.assertFalse(os.path.exists(self.log + ".1"))
        self.assertFalse(os.path.exists(self.log + ".2"))
        self.assertEqual(_lines(self.log), 200)

    # ---------- 2) 小阈值触发轮转 ----------
    def test_small_threshold_triggers_rotation(self):
        mm = self._mm(0.001)                     # ≈1 KB
        for _ in range(60):
            mm._audit("WRITE", 1, 10, "y" * 80)
        self.assertTrue(os.path.exists(self.log + ".1"))
        self.assertLess(os.path.getsize(self.log), 1024 * 4)

    # ---------- 3) 多次轮转只保留 .1 / .2 ----------
    def test_multiple_rotations_keep_two_archives(self):
        mm = self._mm(0.0004)
        for _ in range(300):
            mm._audit("WRITE", 1, 10, "z" * 90)
        self.assertTrue(os.path.exists(self.log + ".1"))
        self.assertTrue(os.path.exists(self.log + ".2"))
        self.assertFalse(os.path.exists(self.log + ".3"))
        # 磁盘占用有界：归档被删到只剩两份，总量远小于写入总量
        self.assertLess(_lines(self.log, self.log + ".1", self.log + ".2"), 300)

    # ---------- 4) 内容连续性：一次轮转不丢任何一行 ----------
    def test_content_continuity_across_single_rotation(self):
        mm = self._mm(0.004)
        marks = []
        for i in range(60):
            mark = "line-%02d-" % i
            marks.append(mark)
            mm._audit("WRITE", 1, 10, mark + "a" * 40)
        mm._audit("FORGET", 2, 20, "tail-mark")
        blob = ""
        for path in (self.log + ".2", self.log + ".1", self.log):
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    blob += f.read()
        self.assertIn("tail-mark", blob)
        for mark in marks:
            self.assertIn(mark, blob)
        self.assertEqual(blob.count("WRITE"), 60)

    # ---------- 5) 并发写入：不产生半行、不损坏归档 ----------
    def test_concurrent_writes_have_no_partial_lines(self):
        mm = self._mm(0.006)

        def worker(k):
            for _ in range(25):
                mm._audit("WRITE", k, 10, "c" * 120)

        threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        total = _lines(self.log, self.log + ".1", self.log + ".2")
        self.assertGreater(total, 0)
        self.assertLessEqual(total, 200)         # 200 次写入，轮转只会更少不会更多
        for path in (self.log, self.log + ".1", self.log + ".2"):
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        self.assertTrue(line.endswith("\n"))
                        self.assertIn("WRITE", line)

    # ---------- 6) 轮转失败不影响记忆写入 ----------
    def test_rotate_failure_does_not_break_write(self):
        mm = self._mm(0.0001)
        mm._audit("WRITE", 1, 10, "a" * 80)      # 先超过阈值
        with mock.patch("os.replace", side_effect=OSError("disk says no")):
            mm._audit("WRITE", 1, 10, "still-written")
        with open(self.log, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("still-written", text)

    # ---------- 7) 写失败（路径不可用）也不抛给调用方 ----------
    def test_write_failure_is_swallowed(self):
        mm = self._mm(0)
        mm.audit_log_path = os.path.join(self.tmp.name, "no-such-dir", "\x00bad")
        mm._audit("WRITE", 1, 10, "x")           # 不抛异常即通过

