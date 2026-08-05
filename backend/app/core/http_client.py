"""健壮 HTTP 客户端工厂。

背景：httpx 默认 trust_env=True 时会调用 macOS/系统代理配置（urllib getproxies），
当系统 NO_PROXY 含畸形条目（如 `fe80::d653:2aff:fe82:7a35.dns`，非合法 IPv6）时，
httpx 会把它构造成代理 mount 键并解析端口失败，导致 `httpx.AsyncClient()` 直接抛
`httpx.InvalidURL`，从而使 LLM / 图片下载等所有外部请求崩溃。

本模块统一提供 `build_async_client`：显式 `trust_env=False`（完全避开系统代理解析），
改为基于干净解析的环境变量手动应用代理（仅对不在 NO_PROXY 中的外部主机），
使应用不受系统畸形代理配置影响，同时保留代理能力。
"""
import ipaddress
import os
from urllib.parse import urlparse

import httpx


def _no_proxy_matches(host: str, no_proxy: str | None) -> bool:
    """判断 host 是否命中 NO_PROXY（本地回环 / 域名后缀 / IP / CIDR）。畸形条目忽略。"""
    if not no_proxy:
        return False
    host = (host or "").lower().rstrip(".")
    for raw in no_proxy.split(","):
        entry = raw.strip().lower().rstrip(".")
        if not entry:
            continue
        if entry == "*":
            return True
        if entry.startswith("."):
            entry = entry[1:]
        if entry.startswith("*."):
            entry = entry[2:]
        if host == entry or host.endswith("." + entry):
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            continue
        try:
            if "/" in entry:
                if address in ipaddress.ip_network(entry, strict=False):
                    return True
            elif address == ipaddress.ip_address(entry):
                return True
        except ValueError:
            # 畸形条目（如 fe80::...dns）直接忽略，避免 httpx 解析崩溃
            continue
    return False


def env_proxy_for_url(target_url: str) -> str | None:
    """返回 target_url 应使用的代理地址；本机回环 / NO_PROXY 命中时返回 None。"""
    parsed = urlparse(target_url)
    scheme = (parsed.scheme or "http").lower()
    host = parsed.hostname or ""
    if _no_proxy_matches(host, os.environ.get("NO_PROXY") or os.environ.get("no_proxy")):
        return None
    if scheme == "https":
        candidate = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or ""
        )
    else:
        candidate = (
            os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or ""
        )
    candidate = candidate or os.environ.get("ALL_PROXY") or os.environ.get("all_proxy") or ""
    if not candidate:
        return None
    try:
        proxy = urlparse(candidate)
        if proxy.scheme and proxy.hostname:
            return candidate
    except ValueError:
        return None
    return None


def build_async_client(target_url: str, timeout: float | int | None = None, **kwargs) -> httpx.AsyncClient:
    """创建不会因系统畸形代理配置而崩溃的 httpx.AsyncClient。

    显式传入 transport（如测试的 MockTransport）时跳过代理——httpx 中代理 mount
    优先级高于 transport，两者同时存在会导致请求走代理而非指定 transport。
    """
    proxy = None if kwargs.get("transport") else env_proxy_for_url(target_url)
    return httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=proxy, **kwargs)
