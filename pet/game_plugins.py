# -*- coding: utf-8 -*-
"""互动游戏插件系统：目录约定式发现 + 动态加载。

约定：程序所在目录（源码=项目根 / 打包=exe 旁）下的 `互动插件/` 文件夹，
每个子文件夹是一个插件包，包内 `plugin.py` 必须暴露：
    TITLE: str                      菜单显示名
    def create(cfg, parent=None) -> QWidget   打开游戏窗口的工厂（cfg=Config，一般用不到）
可选 DESCRIPTION: str。一个插件坏了只跳过它自己，不影响菜单和别的插件。
"""
import importlib.util
import os
import sys
import builtins
import hashlib
import types

from dataclasses import dataclass

PLUGIN_DIR_NAME = "互动插件"


def plugin_root() -> str:
    """插件根目录：frozen=exe 旁（用户可自行放入）；源码=项目根。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, PLUGIN_DIR_NAME)


@dataclass
class GamePlugin:
    name: str          # 唯一名（内置用 builtin:xxx，插件用文件夹名）
    title: str         # 显示名
    module: object     # 已加载的模块
    description: str = ""


def builtin_games() -> list[GamePlugin]:
    """内置游戏（pet/games/，随 exe 打包，开箱即玩）。"""
    from .games import BUILTIN_GAMES
    return [GamePlugin(name=f"builtin:{m.__name__}",
                       title=str(getattr(m, "TITLE", m.__name__)),
                       module=m,
                       description=str(getattr(m, "DESCRIPTION", "") or ""))
            for m in BUILTIN_GAMES]


def all_games() -> list[GamePlugin]:
    """菜单用：内置游戏在前，外部插件在后。"""
    return builtin_games() + discover()


# 最近一次扫描失败的插件 {文件夹名: 原因}——exe 无控制台，菜单据此给用户看
load_errors: dict[str, str] = {}
_cache: dict = {"sig": None, "plugins": []}


def _scan_signature(root: str):
    """插件目录指纹：各 plugin.py 及同目录 .py 的 (路径, mtime, 大小)。没变化就不重新执行插件代码。"""
    sig = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isfile(os.path.join(d, "plugin.py")):
            continue
        for base, dirs, files in os.walk(d):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            for f in sorted(files):
                if f.endswith(".py"):
                    file = os.path.join(base, f)
                    st = os.stat(file)
                    sig.append((name, os.path.relpath(file, d), st.st_mtime_ns, st.st_size))
    return (root, tuple(sig))


def discover(force: bool = False) -> list[GamePlugin]:
    """扫描插件目录，返回可用的插件列表（加载失败/协议不符的跳过）。
    结果按目录指纹缓存：菜单每次打开都会调用，插件文件没变就不重复执行插件代码。"""
    root = plugin_root()
    if not os.path.isdir(root):
        load_errors.clear()
        _cache.update(sig=None, plugins=[])
        return []
    try:
        sig = _scan_signature(root)
    except OSError:
        sig = None
    if not force and sig is not None and sig == _cache["sig"]:
        return list(_cache["plugins"])
    out: list[GamePlugin] = []
    load_errors.clear()
    for name in sorted(os.listdir(root)):
        entry = os.path.join(root, name, "plugin.py")
        if not os.path.isfile(entry):
            continue
        try:
            mod = _load(entry, f"qy_game_{name}")
            title = getattr(mod, "TITLE", None)
            create = getattr(mod, "create", None)
            if not isinstance(title, str) or not title or not callable(create):
                load_errors[name] = "缺少 TITLE 或 create"
                print(f"[game_plugins] {name} 缺少 TITLE/create，跳过")
                continue
            out.append(GamePlugin(name=name, title=title, module=mod,
                                  description=str(getattr(mod, "DESCRIPTION", "") or "")))
        except KeyboardInterrupt:
            raise
        except BaseException as e:   # 含 SystemExit：插件里调 sys.exit() 不能把整个桌宠带走
            load_errors[name] = f"{type(e).__name__}: {e}"
            print(f"[game_plugins] 加载 {name} 失败（跳过）: {e}")
    _cache.update(sig=sig, plugins=out)
    return list(out)


def _load(path: str, mod_name: str):
    return _load_namespaced(path)


def _load_namespaced(path):
    """每次加载独立包；插件的旧窗口持有旧模块，新窗口使用新版本。"""
    directory = os.path.dirname(os.path.abspath(path))
    namespace = "_qingyan_plugin_" + hashlib.sha256(directory.encode()).hexdigest()[:16]
    namespace += "_" + str(id(object())) + "_" + str(__import__('time').time_ns())
    package = types.ModuleType(namespace)
    package.__path__ = [directory]
    sys.modules[namespace] = package
    modules = {}
    loading = [True]
    native_import = builtins.__import__

    def load_local(name):
        full = namespace + "." + name
        if full in modules:
            return modules[full]
        base = os.path.join(directory, *name.split("."))
        is_package = os.path.isfile(os.path.join(base, "__init__.py"))
        file = os.path.join(base, "__init__.py") if is_package else base + ".py"
        spec = importlib.util.spec_from_file_location(full, file,
            submodule_search_locations=[base] if is_package else None)
        module = importlib.util.module_from_spec(spec)
        modules[full] = module
        if loading[0]:
            sys.modules[full] = module
        module.__dict__["__builtins__"] = dict(vars(builtins), __import__=local_import)
        with open(file, "rb") as f:
            exec(compile(f.read(), file, "exec"), module.__dict__)
        parent_name, _, child = full.rpartition(".")
        parent = modules.get(parent_name) or sys.modules.get(parent_name)
        if parent:
            setattr(parent, child, module)
        return module

    def local_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level:
            full = importlib.util.resolve_name("." * level + name, globals["__package__"])
            local = full[len(namespace)+1:] if full.startswith(namespace + ".") else None
        else:
            local = name
        head = (local or "").split(".")[0]
        # 已加载的标准库/应用名优先，维持既有 json/random 隔离契约。
        if local and (level or head not in sys.modules) and (
            os.path.isfile(os.path.join(directory, head + ".py")) or
            os.path.isfile(os.path.join(directory, head, "__init__.py"))):
            parts = local.split(".")
            for i in range(1, len(parts)+1):
                module = load_local(".".join(parts[:i]))
            for child in fromlist or ():
                if child != "*" and not hasattr(module, child):
                    sub = local + "." + child
                    if os.path.isfile(os.path.join(directory, *sub.split(".")) + ".py"):
                        load_local(sub)
                    elif os.path.isfile(os.path.join(directory, *sub.split("."), "__init__.py")):
                        load_local(sub)
            return module if fromlist else load_local(head)
        return native_import(name, globals, locals, fromlist, level)

    try:
        return load_local("plugin")
    finally:
        loading[0] = False
        # import 闭包持有本版本模块；全局仅在加载期注册，避免缓存随热重载增长。
        for key in list(sys.modules):
            if key == namespace or key.startswith(namespace + "."):
                sys.modules.pop(key, None)


def _legacy_load(path: str, mod_name: str):
    # 插件目录临时入 sys.path：plugin.py 可以 import 同目录的其他模块（如游戏引擎拆分）。
    # 多个插件都有 engine.py 时必须把"当前插件目录"提到 sys.path 最前，
    # 并在加载前后清掉旁路模块的 sys.modules 缓存——否则后来者会拿到别人的引擎。
    # 加载完必须把目录移出 sys.path：否则插件里的 json.py / random.py 会遮蔽整个应用的同名模块。
    plug_dir = os.path.dirname(path)
    # 插件旁路模块使用顶层名导入（如 engine），必须在每次加载前清掉旧插件的同名模块。
    # 只清理当前插件目录中已存在的旁路名，不触碰标准库/应用模块的其他名字。
    siblings = [f[:-3] if f.endswith(".py") else f for f in os.listdir(plug_dir)
                if (f.endswith(".py") and f != "plugin.py")
                or os.path.isfile(os.path.join(plug_dir, f, "__init__.py"))]
    for name in siblings:
        for key in list(sys.modules):
            if (key == name or key.startswith(name + ".")) and _is_plugin_module(sys.modules.get(key)):
                sys.modules.pop(key, None)
    sys.path.insert(0, plug_dir)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        try:
            sys.path.remove(plug_dir)
        except ValueError:
            pass
        for name in siblings:
            for key in list(sys.modules):
                if (key == name or key.startswith(name + ".")) and _is_plugin_module(sys.modules.get(key)):
                    sys.modules.pop(key, None)
    return mod


def _module_in(mod, directory: str) -> bool:
    f = getattr(mod, "__file__", None) or ""
    return bool(f) and os.path.normcase(os.path.dirname(os.path.abspath(f))) == \
         os.path.normcase(os.path.abspath(directory))


def _is_plugin_module(mod) -> bool:
    """只识别插件目录加载的顶层旁路模块，绝不清理标准库/应用模块。"""
    f = getattr(mod, "__file__", None) or ""
    if not f:
        return False
    try:
        root = os.path.normcase(os.path.abspath(plugin_root()))
        directory = os.path.normcase(os.path.abspath(os.path.dirname(f)))
        return os.path.commonpath((root, directory)) == root and directory != root
    except (OSError, ValueError):
        return False


def open_game(plugin: GamePlugin, cfg):
    """创建并显示游戏窗口，返回窗口实例（调用方持有防 GC）。"""
    path = getattr(plugin.module, "__file__", "")
    win = plugin.module.create(cfg)
    win.show()
    win.raise_()
    win.activateWindow()
    return win


def _create_plugin_window(path, cfg):
    return _load(path, "qy_game_create").create(cfg)
