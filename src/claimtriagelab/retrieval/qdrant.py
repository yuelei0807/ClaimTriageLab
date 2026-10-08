"""Qdrant Cloud Inference adapter using its public REST API."""

from __future__ import annotations

import os
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx

DEFAULT_MODEL = "sentence-transformers/all-minilm-l6-v2"


class QdrantConfigurationError(RuntimeError):
    """Raised when Qdrant is not configured for production execution."""


class QdrantEvidenceIndex:
    """Index and search synthetic evidence with free Qdrant Cloud Inference."""

    def __init__(self, url: str, api_key: str, collection: str) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.collection = collection
        self.model = os.getenv("QDRANT_EMBEDDING_MODEL", DEFAULT_MODEL)
        self._ready = False

    @classmethod
    def from_environment(cls) -> QdrantEvidenceIndex:
        url = os.getenv("QDRANT_URL", "")
        key = os.getenv("QDRANT_API_KEY", "")
        if not url or not key:
            raise QdrantConfigurationError("QDRANT_URL and QDRANT_API_KEY are required")
        return cls(url, key, os.getenv("QDRANT_COLLECTION", "claim-evidence"))

    @property
    def headers(self) -> dict[str, str]:
        return {"api-key": self.api_key, "Content-Type": "application/json"}

    def ensure_collection(self) -> None:
        if self._ready:
            return
        response = httpx.get(
            f"{self.url}/collections/{self.collection}", headers=self.headers, timeout=20
        )
        if response.status_code == 404:
            response = httpx.put(
                f"{self.url}/collections/{self.collection}",
                headers=self.headers,
                json={"vectors": {"evidence": {"size": 384, "distance": "Cosine"}}},
                timeout=30,
            )
        response.raise_for_status()
        index_response = httpx.put(
            f"{self.url}/collections/{self.collection}/index",
            headers=self.headers,
            params={"wait": "true"},
            json={"field_name": "case_id", "field_schema": "keyword"},
            timeout=30,
        )
        index_response.raise_for_status()
        self._ready = True

    def index_case(self, case_id: str, records: list[dict[str, Any]]) -> None:
        self.ensure_collection()
        points = []
        for record in records:
            evidence_id = str(record["evidence_id"])
            text = " | ".join(
                f"{key}: {value}"
                for key, value in record.items()
                if value not in (None, "", [], {})
            )
            points.append(
                {
                    "id": str(uuid5(NAMESPACE_URL, f"{case_id}:{evidence_id}")),
                    "vector": {"evidence": {"text": text, "model": self.model}},
                    "payload": {
                        "case_id": case_id,
                        "evidence_id": evidence_id,
                        "field_name": record.get("field_name"),
                        "text": text,
                    },
                }
            )
        if not points:
            return
        response = httpx.put(
            f"{self.url}/collections/{self.collection}/points",
            headers=self.headers,
            params={"wait": "true"},
            json={"points": points},
            timeout=60,
        )
        response.raise_for_status()

    def search(self, case_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self.ensure_collection()
        response = httpx.post(
            f"{self.url}/collections/{self.collection}/points/query",
            headers=self.headers,
            json={
                "query": {"text": query, "model": self.model},
                "using": "evidence",
                "filter": {"must": [{"key": "case_id", "match": {"value": case_id}}]},
                "limit": min(max(limit, 1), 10),
                "with_payload": True,
            },
            timeout=60,
        )
        response.raise_for_status()
        points = response.json().get("result", {}).get("points", [])
        return [
            {
                "evidence_id": point.get("payload", {}).get("evidence_id"),
                "field_name": point.get("payload", {}).get("field_name"),
                "text": point.get("payload", {}).get("text"),
                "score": point.get("score"),
            }
            for point in points
        ]
