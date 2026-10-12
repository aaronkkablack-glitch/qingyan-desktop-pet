"""网络请求公共配置。桌宠的测试和工具回传请求都固定绕过系统代理。"""
import urllib.request


DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
