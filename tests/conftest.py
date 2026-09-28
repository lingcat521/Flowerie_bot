"""全局测试隔离：防止各测试把夹具自带的 SDK 副本留在 sys.path / sys.modules。

背景：`tests/plugins/{doc_example,gap_echo,sdk_plugin}/flowerie_sdk` 是夹具插件自带的
SDK 副本。某个测试把它们插进 `sys.path` 并 import 之后，`flowerie_sdk` 会驻留在
`sys.modules`；后续按名字 import 的测试（如 `tests/test_api_gap_consistency.py` 的
SDK 符号一致性检查）就会拿到那份旧副本 → 随收集顺序随机失败
（2026-09-29 文档重排改了文件系统顺序后 CI 复现，3 failed）。

这里在每个测试结束后（含失败/异常）恢复 `sys.path` 与 `flowerie_sdk*` 的
`sys.modules` 快照，把「谁先跑」变回无关变量。
"""
import sys

import pytest

_SDK = "flowerie_sdk"


def _sdk_modules():
    return {name: mod for name, mod in sys.modules.items()
            if name == _SDK or name.startswith(_SDK + ".")}


@pytest.fixture(autouse=True)
def _isolate_flowerie_sdk():
    saved_path = list(sys.path)
    saved_modules = _sdk_modules()
    try:
        yield
    finally:
        sys.path[:] = saved_path
        for name in list(sys.modules):
            if name == _SDK or name.startswith(_SDK + "."):
                del sys.modules[name]
        sys.modules.update(saved_modules)

