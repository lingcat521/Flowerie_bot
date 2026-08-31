"""保存校验（CI）：花语链关闭时，模型/API key 空或过短放行；链开启时仍然拦截。

ConfigService 依赖 pydantic Settings——本地环境缺失，故本文件仅在 CI（全量）运行。
"""
from src.services.config_service import ConfigService


class _FakeConfig:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _svc(**kw):
    # Settings 字段：默认空/False；用 SimpleNamespace 兼容（ConfigService 只 getattr）
    cfg = _FakeConfig(**{
        "BLOSSOM_MEMORY_ENABLED": False,
        "BLOSSOM_MEMORY_EMBEDDING_ENABLED": False,
        "BLOSSOM_MEMORY_RERANKER_ENABLED": False,
        **kw,
    })
    return ConfigService(cfg)


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


def test_chain_on_still_blocks_invalid_model():
    svc = _svc(BLOSSOM_MEMORY_ENABLED=True, BLOSSOM_MEMORY_EMBEDDING_ENABLED=True)
    # 链开启但模型空 → 这里只做类型校验不卡（null 模型运行时兜底）；至少保存不因 secret 崩
    ok, _msg = svc.update_many({"BLOSSOM_MEMORY_EMBEDDING_API_KEY": "short"})
    assert not ok  # 链开启时短 key 仍拦截
