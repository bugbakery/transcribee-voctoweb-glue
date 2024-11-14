import json
from typing import Any
import httpx

class VocPublishingApiClient:
    def __init__(self, base_url: str, token: str):
        self._base_url = base_url
        self._client = httpx.AsyncClient()
        self._token = token

    def _get_headers(self):
        return {
            "Authorization": f"Token token={self._token}"
        }

    def _get_url(self, url):
        return self._base_url + url

    async def _post(self, url, params={}, **kwargs):
        req = await self._client.post(
            self._get_url(url),
            **kwargs,
            headers=self._get_headers(),
        )

        req.raise_for_status()
        return req

    async def _put(self, url, params={}, **kwargs):
        req = await self._client.put(
            self._get_url(url),
            **kwargs,
            headers=self._get_headers(),
        )

        req.raise_for_status()
        return req

    async def _get(self, url, params={}):
        req = await self._client.get(
            self._get_url(url), headers=self._get_headers(), params=params, timeout=120
        )
        req.raise_for_status()
        return req

    async def get_conference(self, conference: str) -> Any:
        req = await self._get(
            f"/{conference}"
        )

        return req.json()

    async def get_event(self, conference: str, event: str) -> Any:
        req = await self._get(
            f"/{conference}/events/{event}"
        )

        return req.json()

    async def upload_file(self, conference: str, event: str, file_name: str, file_mime_type: str, file_content: httpx._types.FileContent, meta: dict):
        req = await self._put(
            f"/{conference}/events/{event}/file",
            files={
                'file': (file_name, file_content, file_mime_type),
                'meta': (None, json.dumps(meta), 'application/json')
            },
        )

        return req.json()

    async def upload_vtt(self, conference: str, event: str, vtt: str, language: str):
        req = await self.upload_file(
            conference,
            event,
            file_content=vtt,
            file_name="dummy.vtt",
            file_mime_type="text/vtt",
            meta={
                "recording": {
                    "language": language,
                    "mime_type": "text/vtt",
                }
            }
        )

        return req
