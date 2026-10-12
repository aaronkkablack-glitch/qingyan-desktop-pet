"""桌宠程序入口：python -m pet.main

组装：Config / ScheduleStore / GlmClient / PetWindow / ChatPanel /
UsagePanel / ScheduleDialog / 托盘 / 提醒调度。
"""
import os
import sys

from PySide6.QtCore import QLockFile, QTimer, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .chat_panel import ChatPanel
from .config import Config
from .glm_client import GlmClient
from .animation import AVATARS
from . import theme
from .pet_window import PetWindow
from .reminders import ScheduleMonitor, WaterReminder
from .schedule_dialog import ScheduleDialog
from .schedule_store import ScheduleStore
from .usage_panel import UsagePanel


def _bring_up(w):
    w.show()
    w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
    w.raise_()
    w.activateWindow()


def build_menu(cfg, pet, chat, usage, sched, water, monitor) -> "callable":
    # 持有已打开的游戏窗口防 GC：必须在菜单之外——右键菜单关闭后会被 deleteLater
    _games = {"wins": []}

    def fill(menu: QMenu):
        # clear() 不删除 addMenu() 建的子菜单（父对象仍是 menu），显式释放防累积
        for sub in menu.findChildren(QMenu):
            sub.deleteLater()
        menu.clear()
        # 头部实时用量摘要（禁用项，纯展示；菜单每次打开时重建现查）
        usage_header = menu.addAction("📊 用量统计中…")
        usage_header.setEnabled(False)
        from . import usage_reader
        try:
            d = usage_reader.zcode_usage(cfg["zcode_db_path"])
            if not d.get("error"):
                t, w = d["today"], d["week"]

                def fmt(n):
                    n = float(n or 0)
                    return f"{n/1e6:.1f}M" if n >= 1e6 else (f"{n/1e3:.0f}K" if n >= 1e3 else str(int(n)))

                usage_header.setText(f"📊 今日 {fmt(t['total'])} · 本周 {fmt(w['total'])} tokens")
        except Exception:
            pass
        menu.addSeparator()
        a = menu.addAction("💬 和清言聊天")
        a.triggered.connect(lambda: _bring_up(chat))
        a = menu.addAction("📊 Token 用量")
        a.triggered.connect(lambda: _bring_up(usage))
        a = menu.addAction("🗓️ 日程管理…")
        a.triggered.connect(lambda: _bring_up(sched))
        menu.addSeparator()
        w = cfg["water"]
        aw = menu.addAction(f"💧 喝水提醒：{'开' if w['enabled'] else '关'}（间隔在⚙设置里改）")
        aw.triggered.connect(lambda: _toggle_water())
        portrait_menu = menu.addMenu("👒 切换立绘")
        for png, label in (("少女.png", "少女"), ("成女.png", "成女")):
            act = portrait_menu.addAction(label)
            act.triggered.connect(lambda _=False, f=png: pet.set_portrait(f))
        menu.addSeparator()
        from .animation import SPRITE_STATES
        act_menu = menu.addMenu("🎭 动作")
        STATE_ZH = {"idle": "待机", "sleeping": "睡觉", "recording": "聆听", "thinking": "思考",
                    "done": "庆祝", "error": "出错", "dragging": "拖拽"}
        for st in SPRITE_STATES:
            if st == "walking":
                continue  # 桌宠没有走路场景，不进菜单
            act = act_menu.addAction(STATE_ZH.get(st, st))
            act.triggered.connect(lambda _=False, s=st: pet.set_sprite_state(s))
        menu.addSeparator()

        def _fill_games(gmenu):
            from . import game_plugins
            games = game_plugins.all_games()      # 内置在前，外部插件在后（外部按目录指纹缓存）
            gmenu.clear()
            if not games:
                a = gmenu.addAction("（把游戏插件放入「互动插件」文件夹）")
                a.setEnabled(False)
                return
            for pl in games:
                a = gmenu.addAction(f"🎮 {pl.title}")
                if pl.description:
                    a.setToolTip(pl.description)
                a.triggered.connect(lambda _=False, p=pl: _launch(p))
            # exe 没有控制台：加载失败的插件在菜单里给出提示（悬停看原因）
            for name, why in game_plugins.load_errors.items():
                a = gmenu.addAction(f"⚠ {name} 加载失败：{why[:60]}")
                a.setEnabled(False)

        def _launch(p):
            from . import game_plugins
            try:
                win = game_plugins.open_game(p, cfg)
                _games["wins"] = [w for w in _games["wins"] if w.isVisible()] + [win]
                win.pet_hooks = _game_state      # 可选联动钩子：游戏播桌宠动作（老插件忽略）
                _game_state("thinking")
            except Exception as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(None, "互动插件", f"「{p.title}」打开失败：{e}")

        def _game_state(state):
            """互动游戏联动桌宠动作：进行中=思考 / 清言方胜=庆祝 / 败=出错 / 结束=待机。
            走 request（立绘模式不打断）。"""
            mapping = {"thinking": "thinking", "win": "done", "lose": "error", "idle": "idle"}
            pet.request_sprite_state(mapping.get(state, "idle"), "game")

        game_menu = menu.addMenu("🎮 互动")
        game_menu.aboutToShow.connect(lambda: _fill_games(game_menu))   # 展开时才扫描插件
        menu.addSeparator()
        a = menu.addAction("⚙ 设置")
        a.triggered.connect(lambda: _open_pet_settings())
        a = menu.addAction("❌ 退出")
        a.triggered.connect(QApplication.instance().quit)

    def _open_pet_settings():
        """桌宠全局设置（独立窗口）：开机自启 / 喝水提醒。与聊天窗的专项设置互不相干。"""
        from .pet_settings import PetSettingsDialog
        dlg = PetSettingsDialog(cfg, pet)
        if dlg.exec():
            water.restart()

    def _toggle_water():
        cfg["water"]["enabled"] = not cfg["water"]["enabled"]
        try:
            cfg.save()
        except OSError as e:   # 如 API Key 解密失败后锁写：开关本次运行仍生效，只是不落盘
            print(f"[config] 保存失败，喝水开关仅本次运行有效：{e}")
        water.restart()

    return fill


def start_freelane(cfg):
    """启动内嵌白嫖代理（仅监听本机回环），并按 config 应用通道值。

    - 代理常驻：开关（cfg['freelane']['enabled']）关着时它只是躺着，不出网、不产生流量；
    - enabled=True 时把 api_base/api_key/chat_model 覆盖为本地代理值（内存态，退出时随
      cfg.save 落盘，幂等——旧版"外部脚本改配置被退出回写覆盖"的问题由此根除）；
    - 代理起不来不阻塞桌宠启动（聊天时会以明确错误呈现）。
    """
    try:
        from freelane.freelane import FreelaneProxy
        from .config import DATA_DIR
        fl = cfg.get("freelane") or {}
        proxy = FreelaneProxy(data_dir=DATA_DIR,
                              fallback_model=fl.get("fallback_model"),
                              aliases=fl.get("aliases"))
        port = proxy.start(preferred_port=int(fl.get("port") or 8787))
        if not port:
            return None
        if fl.get("enabled"):
            model = str(fl.get("model") or fl.get("fallback_model") or "space-bunny-free")
            cfg["api_base"] = f"http://127.0.0.1:{port}/v1"
            cfg["api_key"] = "freelane"
            cfg["chat_model"] = model   # 免费模型由 freelane.model 管理，不写进自定义模型列表
        return proxy
    except Exception as e:
        print(f"[freelane] 启动失败：{e}")
        return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("清言V1.0")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    import hashlib
    pipe_name = "qingyan-" + hashlib.sha256(os.path.abspath(
        os.environ.get("TEMP", os.getcwd())).casefold().encode()).hexdigest()[:20]

    lock = QLockFile(os.path.join(os.environ.get("TEMP", os.getcwd()), "glm_desktoppet.lock"))
    if not lock.tryLock(200):
        sock = QLocalSocket()
        sock.connectToServer(pipe_name)
        if sock.waitForConnected(300):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(300)
        print("桌宠已在运行（如确认没有，删掉 %TEMP%/glm_desktoppet.lock）")
        return 0

    activate_server = QLocalServer(app)
    QLocalServer.removeServer(pipe_name)
    if not activate_server.listen(pipe_name):
        raise RuntimeError("单实例唤起服务启动失败：" + activate_server.errorString())
    cfg = Config()
    freelane_proxy = start_freelane(cfg)   # 白嫖通道内嵌代理（是否走它由 config 决定）
    store = ScheduleStore()
    glm = GlmClient(cfg)
    pet = PetWindow(cfg)
    chat = ChatPanel(cfg, glm, store)
    usage = UsagePanel(cfg)
    sched = ScheduleDialog(store)

    pet.request_chat.connect(lambda: _bring_up(chat))
    pet.request_usage.connect(lambda: _bring_up(usage))
    pet.request_schedule.connect(lambda: _bring_up(sched))

    water = WaterReminder(cfg)
    monitor = ScheduleMonitor(store)
    pet.menu_builder = build_menu(cfg, pet, chat, usage, sched, water, monitor)

    # 喝水提醒上下文：让清言能准确回答"下次喝水是什么时候"（此前她只能瞎猜）
    def _water_context():
        nxt = water.next_at()
        if not cfg["water"].get("enabled") or nxt is None:
            return "喝水提醒当前未启用。"
        return (f"喝水提醒：每 {cfg['water'].get('interval_min', 45)} 分钟一次"
                f"（{cfg['water'].get('active_start', 9)}-{cfg['water'].get('active_end', 22)} 点），"
                f"下一次约 {nxt:%H:%M}。")

    def refresh_runtime_config():
        water.restart()
        pet.refresh_sleep_config()
        if freelane_proxy:
            fl = cfg.get("freelane") or {}
            freelane_proxy.update_config(fl.get("fallback_model"), fl.get("aliases"))

    chat.set_water_provider(_water_context)
    chat.set_activity_hook(pet.activity)   # 聊天打字/收发消息 → 顺延桌宠睡觉倒计时
    chat.runtime_config_refresh = refresh_runtime_config
    chat.toolhost.set_notifier(refresh_runtime_config)  # 聊天工具改设置后即时生效

    tray = QSystemTrayIcon()
    tray.setToolTip("清言V1.0")

    def refresh_tray_icon(*_):
        # 通知区域空间很小，固定使用清晰的头像图，不显示整身动画帧。
        from .config import ASSETS_DIR
        portrait_icon = os.path.join(ASSETS_DIR, "成女头像.png")
        source = QIcon(portrait_icon) if os.path.isfile(portrait_icon) else QIcon(
            os.path.join(ASSETS_DIR, "app.ico"))
        tray.setIcon(source)
    refresh_tray_icon()

    tray_menu = QMenu()
    pet.menu_builder(tray_menu)
    # 菜单每次打开时重建：用量摘要/喝水开关状态等始终最新
    tray_menu.aboutToShow.connect(lambda: pet.menu_builder(tray_menu))
    tray_menu.setStyleSheet(theme.menu_qss())
    tray.setContextMenu(tray_menu)
    tray.activated.connect(lambda reason: _bring_up(chat)
                           if reason == QSystemTrayIcon.DoubleClick else None)
    tray.show()

    def activate_existing():
        while activate_server.hasPendingConnections():
            conn = activate_server.nextPendingConnection()
            if conn:
                _bring_up(chat)
                conn.disconnectFromServer()
                conn.deleteLater()
    activate_server.newConnection.connect(activate_existing)
    QTimer.singleShot(0, activate_existing)

    def refresh_tooltip():
        from . import usage_reader
        try:
            d = usage_reader.zcode_usage(cfg["zcode_db_path"])
            if not d.get("error"):
                t, w = d["today"], d["week"]

                def fmt(n):
                    n = float(n or 0)
                    return f"{n/1e6:.1f}M" if n >= 1e6 else (f"{n/1e3:.0f}K" if n >= 1e3 else str(int(n)))

                tray.setToolTip(f"清言V1.0\n今日 {fmt(t['total'])} / 本周 {fmt(w['total'])} tokens")
        except Exception:
            pass

    tip_timer = QTimer(app)
    tip_timer.setInterval(5 * 60 * 1000)
    tip_timer.timeout.connect(refresh_tooltip)
    tip_timer.start()
    refresh_tooltip()

    monitor.upcoming.connect(lambda e, m: pet.say(
        f"⏰ 再过 {m} 分钟（{e['start']}）：{e.get('plan') or e['title']}", 9000, sticky=True))
    monitor.starting.connect(lambda e: pet.say(
        f"到点啦！现在开始：{e.get('plan') or e['title']}", 9000, sticky=True))
    water.fired.connect(lambda: pet.say(WaterReminder.random_line(), 9000, sticky=True))

    # 悬停报时：现在是几点、应该做什么（计划优先，无计划按块类别）
    import datetime as _dt

    def _status_text():
        now = _dt.datetime.now()
        hm = f"{now:%H:%M}"
        active, nxt, _delta = store.active_and_next(now)
        if active:
            plan = (active.get("plan") or "").strip()
            title = active.get("title", "")
            if plan:
                what = plan
            elif "学习" in title:
                what = "学习"
            elif "课间" in title:
                what = "课间休息，站起来走走"
            elif "午休" in title:
                what = "午休"
            elif "晚休" in title:
                what = "晚休"
            else:
                what = title
            return f"现在是{hm}，应该{what}啦，主人~"
        if nxt:
            label = (nxt.get("plan") or "").strip() or nxt.get("title", "")
            return f"现在是{hm}，下一场 {nxt['start']} 才到（{label}），现在是自由时间哦，主人~"
        return f"夜已深了，现在是{hm}，晚安主人~明天见！"

    pet.set_status_provider(_status_text)

    # zcode 联动：zcode 干活时清言思考，一轮完成时庆祝（读 zcode jsonl 日志增长）
    if cfg.get("zcode_hook", True):
        from .zcode_watcher import ZcodeWatcher
        import os as _os
        watcher = ZcodeWatcher(_os.path.expanduser(cfg.get("zcode_log_dir", "~/.zcode/cli/log")))
        watcher.state_changed.connect(lambda s: pet.request_sprite_state(s, "zcode"))
        watcher.start()

    # 清言的状态随对话变化：等待回复时思考，完成庆祝 / 出错懊恼（one-shot 自动回待机）。
    # 联动走 request：立绘模式下不打断用户看立绘（菜单选动作是唯一退出立绘的入口）。
    # 收尾统一听 chat.turn_ended：工具链（非流式线程回传）不经过 glm.finished/failed，
    # 只听 glm 会让 chat=thinking 残留、桌宠永不睡觉。
    glm.thinking_started.connect(lambda: pet.request_sprite_state("thinking", "chat"))
    chat.turn_ended.connect(lambda outcome: pet.request_sprite_state(
        "done" if outcome == "done" else "idle" if outcome == "cancelled" else "error", "chat"))

    def shutdown():
        chat.shutdown()
        try:
            cfg.save()
        finally:
            if freelane_proxy:
                freelane_proxy.stop()
    app.aboutToQuit.connect(shutdown)
    pet.show()
    # WindowStaysOnTopHint 在部分 Windows 环境不生效（桌宠被前台窗口盖住、收不到悬停），
    # 用 Win32 强制 topmost 兜底
    import ctypes
    hwnd = int(pet.winId())
    ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)  # HWND_TOPMOST, NOMOVE|NOSIZE
    QTimer.singleShot(800, lambda: pet.say(
        ("我来啦～我是清言，双击可以聊天哦 👋" if cfg["api_key"] else
         "我来啦～我是清言！双击我可以聊天，右上角「⚙ 接口」里填 API Key 我就会说话啦"),
        7000))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
