import pytest

from app.core.http_client import build_async_client, env_proxy_for_url


@pytest.fixture
def proxy_env(monkeypatch):
    """模拟含畸形 IPv6 条目（fe80::...dns）的代理环境。"""
    monkeypatch.setenv(
        "NO_PROXY",
        "127.0.0.1,localhost,198.18.0.0/15,fe80::d653:2aff:fe82:7a35.dns,.local,::1,example.com",
    )
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1082")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:1082")
    yield


def test_build_async_client_survives_malformed_no_proxy(proxy_env):
    # 畸形 NO_PROXY 条目不应让 httpx 构造客户端崩溃
    assert build_async_client("https://api.deepseek.com/v1/chat/completions", timeout=30) is not None
    assert build_async_client("http://127.0.0.1:8045/v1/chat/completions", timeout=30) is not None


def test_env_proxy_bypasses_localhost(proxy_env):
    assert env_proxy_for_url("http://127.0.0.1:8045/v1/chat/completions") is None


def test_env_proxy_applies_to_external_host(proxy_env):
    assert env_proxy_for_url("https://api.deepseek.com/v1/chat/completions") == "http://127.0.0.1:1082"


def test_env_proxy_bypasses_no_proxy_domain(proxy_env):
    assert env_proxy_for_url("https://api.example.com/v1/chat/completions") is None
    assert env_proxy_for_url("https://sub.example.com/v1/chat/completions") is None


def test_build_async_client_without_proxy_env(monkeypatch):
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    assert build_async_client("https://api.anthropic.com/v1/messages", timeout=30) is not None
