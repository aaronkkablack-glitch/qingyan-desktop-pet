"""全局配置：config.json 读写与默认值。

路径分两类（PyInstaller onefile 打包后依然成立）：
- 只读资源（assets / 静态图）：frozen 时从解压目录 sys._MEIPASS 读；
- 用户数据（config.json / data/）：exe 旁边的目录（绿色便携），不可写时退到 %APPDATA%/清言桌宠。
"""
import copy
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FROZEN = getattr(sys, "frozen", False)          # PyInstaller 打包后 True


def _pick_app_dir():
    """用户数据目录：优先 exe/项目根旁（便携），只读时退 %APPDATA%。"""
    base = os.path.dirname(sys.executable) if _FROZEN else _ROOT
    try:
        os.makedirs(base, exist_ok=True)
        probe = os.path.join(base, ".write_probe")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return base
    except OSError:
        appdata = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "清言桌宠")
        os.makedirs(appdata, exist_ok=True)
        return appdata


_BUNDLE_ROOT = sys._MEIPASS if _FROZEN else _ROOT   # 打包进去的只读资源
_APP_DIR = _pick_app_dir()
CONFIG_PATH = os.path.join(_APP_DIR, "config.json")
DATA_DIR = os.path.join(_APP_DIR, "data")
ASSETS_DIR = os.path.join(_BUNDLE_ROOT, "assets")
SCHEDULE_PATH = os.path.join(DATA_DIR, "schedule.json")
PET_USAGE_PATH = os.path.join(DATA_DIR, "pet_usage.json")

DEFAULTS = {
    "api_key": "",
    "api_base": "https://open.bigmodel.cn/api/paas/v4",
    "chat_model": "glm-5.3-flash",
    "chat_models": ["glm-5.3-flash", "glm-5.3"],
    # GLM-5.3 系列始终思考、只支持 low/high/max 档位（实测 disabled 会 400）
    "thinking_effort": "low",
    "max_tokens": 2048,
    "avatar": "shao_nv",            # shao_nv | cheng_nv
    "pet_height": 400,
    "animation": "sprite",          # sprite（精灵图动画，默认）| static | sway
    "sprite_assets_dir": os.path.join(_BUNDLE_ROOT, "静态图"),  # mori 产出的精灵图素材目录
    "idle_sleep_min": 5,            # 无互动 N 分钟后进入睡觉状态（0=关闭）
    "zcode_hook": True,             # 联动 zcode：工作中→思考，完成→庆祝
    "zcode_log_dir": os.path.expanduser("~/.zcode/cli/log"),
    "sprite_durations": {"idle": 4600, "sleeping": 5000, "recording": 4000, "thinking": 3000,
                         "done": 1800, "error": 2000, "walking": 4000, "dragging": 4400},
    "pet_pos": None,                # [x, y]，退出时保存
    "water": {"enabled": True, "interval_min": 45, "active_start": 9, "active_end": 22},
    "zcode_db_path": os.path.expanduser("~/.zcode/cli/db/db.sqlite"),  # 各机器自己的用户目录
    "system_prompt": "",            # 留空则用 DEFAULT_PERSONA
    "max_history_messages": 20,
    # 白嫖通道（OpenCode Zen 免费车道，桌宠内嵌本地代理；详见 freelane/freelane.py 与 freelane/说明.md）
    # enabled=False 时为普通自定义 API 模式；切到白嫖时原 API 配置自动快照进 custom，切回时还原
    "freelane": {
        "enabled": False,
        "port": 8787,
        "model": "space-bunny-free",          # 白嫖通道里实际使用的模型
        "fallback_model": "space-bunny-free",  # 被上游拒绝时自动回退目标
        "aliases": {"glm-5.3-flash": "space-bunny-free", "glm-5.3": "space-bunny-free"},
        "custom": {},                          # 切回自定义通道时恢复的 API 配置（自动维护）
    },
}


def backup_corrupt(path: str) -> str | None:
    """读取失败的数据文件改名为 *.corrupt-时间戳 保留现场，避免随后的保存用默认值覆盖它。"""
    import time
    if not os.path.exists(path):
        return None
    dst = f"{path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}"
    try:
        os.replace(path, dst)
        return dst
    except OSError as e:
        print(f"[config] 备份损坏文件失败: {e}")
        return None


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


# 这些配置含用户家目录路径：落盘时反展开成 ~/ 形式——
# 分享/迁移 config 到别的机器/别的用户名时自动跟随本机用户（固化绝对路径会指向不存在的家）
_HOME_KEYS = {"zcode_log_dir", "zcode_db_path"}


def _clamp_int(d: dict, key: str, lo: int, hi: int, default: int) -> None:
    """单项收敛：非数字回落默认值（不抛异常，避免一个坏值让所有 save 失败）。"""
    try:
        v = int(d.get(key, default))
    except (TypeError, ValueError):
        v = default
    d[key] = max(lo, min(hi, v))


def _validate(d: dict) -> None:
    """校验并收敛用户可编辑的数值配置，避免坏配置进入运行态。"""
    _clamp_int(d, "max_tokens", 256, 32768, 2048)
    _clamp_int(d, "max_history_messages", 1, 400, 20)
    _clamp_int(d, "pet_height", 120, 1200, 400)
    if not isinstance(d.get("water"), dict):
        d["water"] = copy.deepcopy(DEFAULTS["water"])
    water = d["water"]
    _clamp_int(water, "interval_min", 5, 240, 45)
    _clamp_int(water, "active_start", 0, 23, 9)
    _clamp_int(water, "active_end", 0, 24, 22)   # 24 = 到午夜；起点 > 终点表示跨夜
    if not isinstance(d.get("freelane"), dict):
        d["freelane"] = copy.deepcopy(DEFAULTS["freelane"])
    _clamp_int(d["freelane"], "port", 1, 65535, 8787)


def _deexpand(d: dict) -> dict:
    home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
    for k in _HOME_KEYS:
        v = d.get(k)
        if not isinstance(v, str):
            continue
        norm = v.replace("\\", "/")
        # 必须整段匹配家目录：C:/Users/x 不能误吃 C:/Users/xavier
        if norm.lower() == home.lower() or norm.lower().startswith(home.lower() + "/"):
            d[k] = "~/" + norm[len(home) + 1:]
    return d


class Config:
    def __init__(self):
        self._data = copy.deepcopy(DEFAULTS)
        self.first_run = not os.path.exists(CONFIG_PATH)
        self.load()
        if self.first_run:
            self.save()  # 首次运行写出默认配置，方便用户直接改 api_key 等字段

    @property
    def d(self) -> dict:
        return self._data

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def get(self, key, default=None):
        return self._data.get(key, default)

    def load(self):
        if not os.path.exists(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("顶层不是对象")
        except OSError as e:
            # 文件在但读不了（杀软/同步盘占用）：禁止本次运行回写，免得默认值覆盖用户配置
            print(f"[config] 读取失败，本次不回写配置: {e}")
            self._no_save = True
            return
        except ValueError as e:  # JSONDecodeError / UnicodeDecodeError 都是 ValueError
            bak = backup_corrupt(CONFIG_PATH)
            if bak is None:
                self._no_save = True
            print(f"[config] 配置损坏，已备份到 {bak}，用默认配置: {e}")
            return
        data = _deep_merge(copy.deepcopy(DEFAULTS), raw)
        if _FROZEN:
            resource = str(data.get("sprite_assets_dir") or "")
            # onefile 的 _MEI 目录属于单次进程，不可沿用上一次落盘的解压路径。
            if not os.path.isdir(resource) or "_MEI" in resource:
                data["sprite_assets_dir"] = DEFAULTS["sprite_assets_dir"]
        # 落盘是 ~/ 反展开形式（分享/迁移友好），加载时还原成本机绝对路径
        for k in _HOME_KEYS:
            v = data.get(k)
            if isinstance(v, str) and v.startswith(("~", "~/")):
                data[k] = os.path.expanduser(v)
        from .credentials import decrypt
        protected = data.pop("api_key_protected", None)
        if protected:
            recovered = decrypt(protected)
            if recovered is None:
                self.credential_error = "无法解密 API Key，请在设置中重新填写；原配置保留"
                self._no_save = True
            data["api_key"] = recovered or ""
        custom = (data.get("freelane") or {}).get("custom")
        if isinstance(custom, dict):
            cprot = custom.pop("api_key_protected", None)
            if cprot:
                recovered = decrypt(cprot)
                if recovered is None:
                    self.credential_error = "无法解密自定义通道 Key，请重新填写；原配置保留"
                    self._no_save = True
                custom["api_key"] = recovered or ""
        _validate(data)
        self._data = data

    @staticmethod
    def _protect_key(holder: dict) -> None:
        """holder["api_key"] → holder["api_key_protected"]（DPAPI）；占位 key 'freelane' 不加密。"""
        from .credentials import encrypt
        key = holder.get("api_key", "")
        if key and key != "freelane":
            protected = encrypt(key)
            if protected is None:
                raise OSError("API Key 加密失败，拒绝明文保存")
            holder["api_key_protected"] = protected
            holder["api_key"] = ""
        else:
            holder.pop("api_key_protected", None)

    def save(self):
        if getattr(self, "_no_save", False):
            raise OSError(getattr(self, "credential_error", "配置无法读取，禁止覆盖原文件"))
        data = copy.deepcopy(self._data)
        if _FROZEN and data.get("sprite_assets_dir") == DEFAULTS["sprite_assets_dir"]:
            data.pop("sprite_assets_dir", None)
        _validate(data)
        self._protect_key(data)
        custom = (data.get("freelane") or {}).get("custom")
        if isinstance(custom, dict):
            self._protect_key(custom)  # 白嫖通道快照的自定义 Key 同样不落明文
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_deexpand(data), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)

    def commit(self, values):
        """成功写盘后才替换运行态；失败保持原对象内容。"""
        old = self._data
        blocked = getattr(self, "_no_save", False)
        # 解密失败允许用户显式重新填写 Key；读取权限失败仍不允许覆盖。
        replacing_credentials = bool(getattr(self, "credential_error", "")) and bool(
            values.get("api_key") and values.get("api_key") != "freelane" or
            ((values.get("freelane") or {}).get("custom") or {}).get("api_key"))
        if replacing_credentials:
            self._no_save = False
        self._data = copy.deepcopy(values)
        try:
            self.save()
        except Exception:
            self._data = old
            self._no_save = blocked
            raise
        if replacing_credentials:
            self.credential_error = ""


DEFAULT_PERSONA = (
    "你是「清言」，住在主人桌面上的 Qwen 看板娘桌宠。性格活泼贴心，说话口语化、"
    "简短可爱（一般不超过两三句）。主人问时间、日程、该干什么时，直接根据给定信息回答。"
    "回答不要写思考过程、不要犹豫，想到就直说。"
)
