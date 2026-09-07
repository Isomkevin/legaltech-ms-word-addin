import httpx
import pytest

from app.services.courtlistener import clear_cache, lookup_citation


class _MockClient:
    def __init__(self, status: int, payload: dict, calls: list):
        self.status = status
        self.payload = payload
        self.calls = calls

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params})
        return httpx.Response(self.status, json=self.payload)

    async def aclose(self):
        return None


@pytest.fixture(autouse=True)
def _clear():
    clear_cache()
    yield
    clear_cache()


@pytest.mark.asyncio
async def test_lookup_hit_and_cache(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")
    from app.core.config import get_settings

    get_settings.cache_clear()
    calls: list = []
    client = _MockClient(
        200,
        {
            "count": 1,
            "results": [
                {
                    "cluster_id": 99,
                    "caseName": "Foo v. Bar",
                    "court": "SCOTUS",
                    "dateFiled": "1964-01-01",
                    "absolute_url": "/opinion/1/",
                }
            ],
        },
        calls,
    )
    first = await lookup_citation("123 U.S. 1", client=client)
    second = await lookup_citation("123 U.S. 1", client=client)
    assert first[0]["status"] == 200
    assert first[0]["clusters"][0]["id"] == 99
    assert first == second
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_lookup_miss_shape(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")
    from app.core.config import get_settings

    get_settings.cache_clear()
    client = _MockClient(200, {"count": 0, "results": []}, [])
    out = await lookup_citation("999 Fake 1", client=client)
    assert out == [{"citation": "999 Fake 1", "status": 404, "clusters": []}]


def test_lookup_no_token_is_503(client, auth_header, monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    client.get("/api/v1/auth/me", headers=auth_header)
    res = client.get("/api/v1/us/citation-lookup?citation=1", headers=auth_header)
    assert res.status_code == 503
    assert res.json()["detail"]["error_code"] == "citation_lookup_unavailable"


def test_lookup_requires_auth(client):
    assert client.get("/api/v1/us/citation-lookup?citation=1").status_code == 401


@pytest.mark.asyncio
async def test_lookup_429(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")
    from app.core.config import get_settings
    from app.core.errors import ApiError

    get_settings.cache_clear()
    client = _MockClient(429, {}, [])
    with pytest.raises(ApiError) as exc:
        await lookup_citation("1 U.S. 1", client=client)
    assert exc.value.status == 429
