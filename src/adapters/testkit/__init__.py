"""Gate E/F 测试用虚拟协议包（不进入生产路径；仅 tests/ 与契约夹具引用）。"""
from src.adapters.testkit.test_protocol import (
    TestProtocolChannel,
    TestProtocolEventParser,
    test_protocol_descriptor,
)

__all__ = ["TestProtocolEventParser", "TestProtocolChannel", "test_protocol_descriptor"]
