"""插件 data_dir 能力：自动创建 plugins/<id>/data/ 且位于插件目录内（防穿越）。"""
import os

from src.plugins.runner.python_runner import PluginRunner


def test_data_dir_auto_created(tmp_path):
    pd = str(tmp_path / "plugins" / "my_plugin")
    os.makedirs(pd, exist_ok=True)
    r = PluginRunner(pd, "plugin.py", "my_plugin")
    assert os.path.isdir(r.data_dir)
    assert os.path.realpath(r.data_dir).startswith(os.path.realpath(pd) + os.sep)


def test_data_dir_in_ctx(tmp_path):
    pd = str(tmp_path / "plugins" / "p2")
    os.makedirs(pd, exist_ok=True)
    r = PluginRunner(pd, "plugin.py", "p2")
    ctx = {"plugin_id": "p2"}
    _ = ctx
    # on_startup ctx 由 run 注入——此处验证属性与路径语义
    assert r.data_dir == os.path.join(os.path.abspath(pd), "data")
