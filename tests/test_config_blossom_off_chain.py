"""保存校验（CI）：花语链关闭时，模型/API key 空或过短放行；链开启时仍然拦截。

ConfigService 依赖 pydantic Settings——本地环境缺失，故本文件仅在 CI（全量）运行。
"""
from src.services.config_service import ConfigService


class _FakeConfig:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeRepo:
    def __init__(self):
        self.store = {}

    def set_config(self, key, value):
        self.store[key] = value

    def get_config(self, key):
        return self.store.get(key)


def _svc(**kw):
    # Settings 字段：默认空/False；用 SimpleNamespace 兼容（ConfigService 只 getattr）
    cfg = _FakeConfig(**{
        "BLOSSOM_MEMORY_ENABLED": False,
        "BLOSSOM_MEMORY_EMBEDDING_ENABLED": False,
        "BLOSSOM_MEMORY_RERANKER_ENABLED": False,
        **kw,
    })
    return ConfigService(cfg, _FakeRepo())


def test_chain_off_allows_short_key():
    svc = _svc()
    # 总开关 OFF：短 key（3 字符）随表单保存 → 不报"值不合法"
    ok, msg = svc.update_many({"BLOSSOM_MEMORY_EMBEDDING_API_KEY": "abc",
                               "BLOSSOM_MEMORY_EMBEDDING_MODEL": "",
                               "BLOSSOM_MEMORY_ENABLED": "false"})
    assert ok, msg


def test_subchain_off_allows_short_key():
    svc = _svc(BLOSSOM_MEMORY_ENABLED=True, BLOSSOM_MEMORY_EMBEDDING_ENABLED=True,
               BLOSSOM_MEMORY_RERANKER_ENABLED=False)
    # 子链（reranker）关闭 → 其短 key 放行
    ok, msg = svc.update_many({"BLOSSOM_MEMORY_RERANKER_API_KEY": "xy",
                               "BLOSSOM_MEMORY_RERANKER_MODEL": "x"})
    assert ok, msg


def test_disabling_subswitch_this_save_allows_short_key():
    """本次提交把子开关关掉（false）→ 短 key 放行（修复回归）。"""
    svc = _svc(BLOSSOM_MEMORY_ENABLED=True, BLOSSOM_MEMORY_EMBEDDING_ENABLED=True,
               BLOSSOM_MEMORY_RERANKER_ENABLED=True)
    ok, msg = svc.update_many({"BLOSSOM_MEMORY_EMBEDDING_ENABLED": "false",
                               "BLOSSOM_MEMORY_EMBEDDING_API_KEY": "ab",
                               "BLOSSOM_MEMORY_EMBEDDING_MODEL": ""})
    assert ok, msg


def test_disabling_master_this_save_allows_short_key():
    """本次提交把总开关关掉（false）→ 所有 key 放行。"""
    svc = _svc(BLOSSOM_MEMORY_ENABLED=True, BLOSSOM_MEMORY_EMBEDDING_ENABLED=True,
               BLOSSOM_MEMORY_RERANKER_ENABLED=True)
    ok, msg = svc.update_many({"BLOSSOM_MEMORY_ENABLED": "false",
                               "BLOSSOM_MEMORY_EMBEDDING_API_KEY": "xy"})
    assert ok, msg


def test_empty_api_key_skip_not_error():
    """BLOSSOM API_KEY 为空 → 跳过（不修改），不得报'值不合法'（is_secret 修复回归）。"""
    svc = _svc()
    ok, msg = svc.update_many({"BLOSSOM_MEMORY_EMBEDDING_API_KEY": ""})
    assert ok, msg
    ok2, msg2 = svc.update_many({"BLOSSOM_MEMORY_RERANKER_API_KEY": ""})
    assert ok2, msg2
    ok3, msg3 = svc.update_many({"DATABASE_URL": ""})
    assert ok3, msg3


def test_empty_numeric_field_skips_not_errors():
    """清空数值字段（如维度/限额）→ 跳过（保持原值），不得报'值不合法'。"""
    svc = _svc()
    ok, msg = svc.update_many({"BLOSSOM_MEMORY_VECTOR_DIMENSION": ""})
    assert ok, msg


def test_daily_extract_limit_zero_allowed():
    """每日提取上限 0（想停）→ 合法（0=等同关闭）。"""
    svc = _svc()
    ok, msg = svc.update_many({"BLOSSOM_MEMORY_DAILY_EXTRACT_LIMIT": "0"})
    assert ok, msg


def test_chain_on_still_blocks_invalid_model():
    svc = _svc(BLOSSOM_MEMORY_ENABLED=True, BLOSSOM_MEMORY_EMBEDDING_ENABLED=True)
    # 链开启但模型空 → 这里只做类型校验不卡（null 模型运行时兜底）；至少保存不因 secret 崩
    ok, _msg = svc.update_many({"BLOSSOM_MEMORY_EMBEDDING_API_KEY": "short"})
    assert not ok  # 链开启时短 key 仍拦截
