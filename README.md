# 清言 V1.0

Windows 桌宠：动画与立绘、日程和喝水提醒、流式聊天及本地工具、四款小游戏和 zcode 用量联动。

## 使用

解压发布包到可写目录，双击 `清言V1.0.exe`。再次启动会请求唤起已有聊天窗口。

- 双击清言打开聊天；回车发送，Shift+回车换行，“停止回复”结束当前请求。
- 拖动调整位置；右键或托盘菜单打开日程、设置、用量和小游戏。
- 长按约 0.7 秒显示当前日程；云朵可点击关闭。
- 喝水/日程确认气泡首次点击只关闭，不触发戳一戳或打断睡觉动作。
- 日程星期为 0–6（0=周一），日期为 YYYY-MM-DD；均留空表示每天，结束早于开始表示跨午夜。
- 聊天窗设置中选择免费或自定义 API 通道。space-bunny-free 已由用户人工确认正常对话；
  上游可用性可能变化，设置功能支持更换通道。自定义 API 地址需为 http/https。

## 数据与凭据

首次运行在 exe 旁生成 `config.json` 和 `data/`；不可写时使用 `%APPDATA%/清言桌宠`。
源码版数据在项目根，与 exe 数据独立。不要把自己的 config/data 发给其他人。
API Key 使用 Windows DPAPI 保护，换机器或 Windows 用户后需要重新填写。
退出前通过托盘“退出”关闭。升级前备份 config/data，只替换 exe。

## 游戏与插件

内置井字棋、五子棋、象棋和斗地主。规则见 [游戏规则.md](游戏规则.md)。象棋采用皮卡鱼
程序棋规裁决，棋力仍由 Python AI 提供；规则子程序 GPLv3 源码随发布包提供。
插件放到 exe 旁 `互动插件/`。插件直接执行 Python，仅使用可信插件；不存在权限沙箱。

## 开发与构建

使用 Python 3.12.10（Windows x64）：

```powershell
python -m pip install -r requirements-build.txt
python run_checks.py
python -m PyInstaller 清言桌宠.spec
python package_release.py
```

`run_checks.py` 仅运行本地测试。`test_smoke.py` 默认不执行外部模型请求；不要重复探测
已人工验收的 space-bunny-free。发布包只包含白名单文件，不包含个人数据。
详见 [发布与验收.md](发布与验收.md) 和 [开发日志.md](开发日志.md)。
