from tempfile import _TemporaryFileWrapper
from typing import IO, Any, Literal
import httpx
from pydantic.fields import Field
from pydantic.type_adapter import TypeAdapter
from transcribee_voctoweb.transcribee_api.model import (
    BodyCreateDocumentApiV1DocumentsPost,
    CreateShareToken,
    Document,
    DocumentShareTokenBase,
    TaskResponse,
)


class DocumentBodyWithFile(BodyCreateDocumentApiV1DocumentsPost):
    file: IO[bytes] | _TemporaryFileWrapper = Field(..., exclude=True)

    model_config = {
        'arbitrary_types_allowed': True
    }

file_entry_type = tuple[
    str, tuple[str | None, Any] | tuple[str | None, Any, str]
]

class TranscribeeApiClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token
        self.client = httpx.AsyncClient(timeout=10.0)

    def _get_headers(self):
        return {
            "Authorization": f"Token {self.token}",
        }

    def _get_url(self, url):
        return self.base_url + url

    async def _get(self, url, params={}):
        req = await self.client.get(
            self._get_url(url), headers=self._get_headers(), params=params, timeout=120
        )
        req.raise_for_status()
        return req


    async def _post(self, url, **kwargs):
        req = await self.client.post(
            self._get_url(url),
            **kwargs,
            headers=self._get_headers(),
        )

        req.raise_for_status()
        return req

    async def get_tasks_for_document(self, doc_id: str) -> list[TaskResponse]:
        req = await self._get(f"/api/v1/documents/{doc_id}/tasks/")
        adapter = TypeAdapter(list[TaskResponse])
        return adapter.validate_json(req.text)

    async def create_document(self, document: DocumentBodyWithFile) -> Document:
        doc_dict = document.model_dump()
        data = {key: value for key, value in doc_dict.items() if key != "file" and value is not None}

        files: list[file_entry_type] = [
            ("file", ("video.mp4", document.file, "video/mp4")),
        ]

        req = await self._post("/api/v1/documents/", data=data, files=tuple(files))
        return Document.model_validate_json(req.text)

    async def create_share_token(self, doc_id: str, data: CreateShareToken):
        data_dict = data.model_dump()
        req = await self._post(f"/api/v1/documents/{doc_id}/share_tokens/", json=data_dict)
        return DocumentShareTokenBase.model_validate_json(req.text)

    async def export(
        self,
        doc_id: str,
        format: Literal["SRT"] | Literal["VTT"] = "SRT",
        include_speaker_names=False,
        include_word_timing=False,
    ):
        req = await self._get(
            f"/api/v1/documents/{doc_id}/export/",
            params={
                "format": format,
                "include_speaker_names": include_speaker_names,
                "include_word_timing": include_word_timing,
            },
        )
        return req.text
