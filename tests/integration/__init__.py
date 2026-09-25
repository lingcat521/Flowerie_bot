"""实机（real-device）integration test 包 —— 见 tests/integration/README.md。

单独成包的原因：这些用例与 `tests/test_*.py`（unit / 静态测试）**在执行条件上完全不同**——
它们需要真实协议端与测试群，默认 skip，CI 不会把它们当"已通过"。
"""
