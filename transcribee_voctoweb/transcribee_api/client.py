from typing import Any
from pydantic.types import FilePath
import requests
from transcribee_voctoweb.transcribee_api.model import (
    BodyCreateDocumentApiV1DocumentsPost,
    CreateShareToken,
    Document,
    DocumentShareTokenBase,
)


class DocumentBodyWithFile(BodyCreateDocumentApiV1DocumentsPost):
    file: FilePath


class TranscribeeApiClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token

    def _get_headers(self):
        return {
            "Authorization": f"Token {self.token}",
        }

    def post(self, url, **kwargs):
        req = requests.post(
            self._get_url(url),
            **kwargs,
            headers=self._get_headers(),
        )

        req.raise_for_status()
        return req

    def _get_url(self, url):
        return self.base_url + url

    def get(self, url):
        req = requests.get(
            self._get_url(url),
            headers=self._get_headers(),
        )
        req.raise_for_status()
        return req

    def create_document(self, document: DocumentBodyWithFile) -> Document:
        doc_dict = document.model_dump()
        data = {key: value for key, value in doc_dict.items() if key != "file"}

        with open(document.file, "rb") as file:
            file_entry_type = tuple[str, tuple[str | None, Any] | tuple[str | None, Any, str]]
            files: list[file_entry_type] = [
                ("file", ("video.mp4", file, "video/mp4")),
            ]

            for key, value in data.items():
                files.append((key, (None, value)))

            req = self.post("/api/v1/documents/", files=tuple(files))
            return Document.model_validate_json(req.text)

    def create_share_token(self, doc_id: str, data: CreateShareToken):
        data_dict = data.model_dump()
        req = self.post(f"/api/v1/documents/{doc_id}/share_tokens/", json=data_dict)
        return DocumentShareTokenBase.model_validate_json(req.text)