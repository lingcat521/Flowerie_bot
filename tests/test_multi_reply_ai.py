"""Multi-Reply：AI 结构化多条解析（含降级）单测。"""
from src.services.ai_client import AIClient


def test_plain_text_is_not_multi():
    assert AIClient.extract_multi_messages("你好呀") is None
    assert AIClient.extract_multi_messages("") is None
    assert AIClient.extract_multi_messages(None) is None


def test_json_messages_object_is_parsed():
    got = AIClient.extract_multi_messages('{"messages": ["你好呀", "今天怎么样", "最近还好吗"]}')
    assert got == ["你好呀", "今天怎么样", "最近还好吗"]


def test_fenced_json_is_parsed():
    text = chr(96) * 3 + 'json' + chr(10) + '{"messages": ["a", "b"]}' + chr(10) + chr(96) * 3
    assert AIClient.extract_multi_messages(text) == ["a", "b"]


def test_invalid_structures_fall_back_to_none():
    for bad in ['{"messages": "not-a-list"}', '{"nope": 1}', '{"messages": []}',
                '{"messages": ["  ", ""]}', '{broken json', '["a","b"]', '前缀 {"messages":["a"]}']:
        assert AIClient.extract_multi_messages(bad) is None, bad


def test_blank_entries_are_dropped():
    assert AIClient.extract_multi_messages('{"messages": ["a", "  ", "b"]}') == ["a", "b"]
