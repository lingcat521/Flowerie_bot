"""真 WebUI 服务器引导进程（浏览器 E2E 夹具的子进程入口；不是 Mock）。

由 `tests/e2e/_harness.py:launch_server()` 拉起，组装方式与 `main.py` 一致：

    Settings(临时配置) -> SettingsRepository(临时 settings.db)
      -> ConfigService(+ 临时 .env) -> 注册管理员（Bootstrap Lock 的第一个账号）
      -> PluginManager(真插件目录，真子进程) -> refresh() + enable()
      -> WebUIServer.start()（真 aiohttp，监听 127.0.0.1 的临时端口）

就绪后把 `{"ok": true, "port": …}` 写进 --ready-file；收到 SIGTERM/SIGINT 时干净关闭
（WebUIServer.stop() + PluginManager.shutdown()，绝不留孤儿插件进程）。

本文件只用仓库公开面（与 main.py 相同的类），不 Mock Core、不 Mock 插件。
"""
import argparse
import asyncio
import json
import os
import signal
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Flowerie WebUI E2E server bootstrap")
    parser.add_argument("--plugin-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--admin-user", default="e2e-admin")
    parser.add_argument("--admin-password", default="e2e-secret-123")
    parser.add_argument("--enable", action="append", default=[])
    return parser.parse_args(argv)


def build_settings(args):
    """显式构造 Settings：不读仓库 .env（cwd 是临时目录），端口/插件目录全部临时隔离。"""
    from src.config import Settings

    settings = Settings(
        _env_file=None,
        WEB_UI_PORT=args.port,
        WEB_UI_HOST="127.0.0.1",
        WEB_UI_ALLOW_LAN=False,
        WEB_UI_ENABLED=True,
        PLUGIN_DIR=args.plugin_dir,
        SETTINGS_DB_PATH=os.path.join(args.data_dir, "settings.db"),
    )
    return settings


async def run(args) -> int:
    from src.plugins.manager import PluginManager
    from src.repositories.settings_repository import SettingsRepository
    from src.services.config_service import ConfigService
    from src.services.web_ui import WebUIServer

    cfg = build_settings(args)
    repo = SettingsRepository(cfg.SETTINGS_DB_PATH)
    service = ConfigService(cfg, repo, env_path=os.path.join(args.data_dir, ".env"))
    ok, message = service.register_user(args.admin_user, args.admin_password)
    print("[serve] register_user ok=%s message=%s" % (ok, message), flush=True)

    manager = PluginManager(config=cfg, repository=repo)
    discovered = manager.refresh()
    print("[serve] discovered=%s" % (discovered,), flush=True)
    enabled = []
    for pid in args.enable:
        row = manager.get_plugin(pid) or {}
        if not row:
            print("[serve] enable skipped (not discovered): %s" % pid, flush=True)
            continue
        approved = list(row.get("declared_permissions") or [])
        ok, why = await manager.enable(pid, approved_permissions=approved)
        print("[serve] enable %s ok=%s why=%s" % (pid, ok, why), flush=True)
        enabled.append({"id": pid, "ok": bool(ok), "why": str(why),
                        "status": str((manager.get_plugin(pid) or {}).get("status") or "")})

    server = WebUIServer(cfg, service, data_dir=args.data_dir, plugin_manager=manager)
    await server.start()
    info = {
        "ok": True,
        "port": int(args.port),
        "pid": os.getpid(),
        "admin_user": args.admin_user,
        "plugin_dir": args.plugin_dir,
        "plugins": enabled,
        "discovered": list(discovered or []),
    }
    with open(args.ready_file, "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=2)
    print("[serve] READY %s" % json.dumps(info, ensure_ascii=False), flush=True)

    stop = asyncio.Event()

    def _on_signal(signum, _frame):
        print("[serve] signal %s -> shutdown" % signum, flush=True)
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):  # noqa: PERF203 - 非主线程/不支持时忽略
            pass
    try:
        await stop.wait()
    finally:
        await server.stop()
        await manager.shutdown()
        print("[serve] stopped", flush=True)
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    os.makedirs(args.data_dir, exist_ok=True)
    try:
        return asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001 - 启动失败要把真实原因写进日志（父进程会读）
        import traceback
        traceback.print_exc()
        print("[serve] FATAL %s: %s" % (type(exc).__name__, exc), flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
