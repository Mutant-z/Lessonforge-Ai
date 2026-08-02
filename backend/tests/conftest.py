import os
import shutil
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

TEST_ROOT = Path(__file__).parent / ".data"
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
TEST_ROOT.mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_ROOT / 'test.db'}"
os.environ["STORAGE_ROOT"] = str(TEST_ROOT / "storage")
os.environ["SECRET_KEY"] = "test-secret-key-with-at-least-32-characters"

from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            yield http


@pytest.fixture
async def auth_headers(client):
    username = f"teacher_{os.urandom(4).hex()}"
    await client.post("/api/v1/auth/register", json={"username": username, "password": "strong-password"})
    response = await client.post("/api/v1/auth/login", data={"username": username, "password": "strong-password"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

