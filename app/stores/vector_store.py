"""One Chroma directory for the global knowledge base, and one directory per project.

The stores are opened separately and are only combined by the retriever.
"""

from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.api.types import Documents, Embeddings
from chromadb.utils.embedding_functions import EmbeddingFunction, register_embedding_function

from app.stores.embeddings import embed_texts

_store: "VectorStore | None" = None
_store_root: str | None = None


@register_embedding_function
class AppEmbedding(EmbeddingFunction[Documents]):
    """Keeps Chroma from downloading its default ONNX model."""

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        return embed_texts(list(input), kind="passage")

    @staticmethod
    def name() -> str:
        return "engineering-assistant"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "AppEmbedding":
        return AppEmbedding()


def scope_key(scope: str, project_id: str | None, owner_id: str | None = None) -> str:
    if scope == "personal":
        return f"personal_{owner_id or project_id or 'none'}"
    if scope == "global" or not project_id:
        return "global"
    return f"project_{project_id}"


class VectorStore:
    def __init__(self, root: Path):
        self.root = root
        self._clients: dict[str, chromadb.PersistentClient] = {}

    def _collection(self, key: str):
        path = self.root / key
        path.mkdir(parents=True, exist_ok=True)
        if key not in self._clients:
            self._clients[key] = chromadb.PersistentClient(
                path=str(path),
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
        client = self._clients[key]
        return client.get_or_create_collection(
            name="chunks",
            embedding_function=AppEmbedding(),
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, key: str, ids: list[str], texts: list[str], metadatas: list[dict], embeddings: list[list[float]]) -> None:
        if not ids:
            return
        col = self._collection(key)
        # Chroma metadata values must be scalar.
        clean = []
        for meta in metadatas:
            clean.append({k: ("" if v is None else v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in meta.items()})
        col.upsert(ids=ids, documents=texts, metadatas=clean, embeddings=embeddings)

    def delete_ids(self, key: str, ids: list[str]) -> None:
        if not ids:
            return
        col = self._collection(key)
        col.delete(ids=ids)

    def query(self, key: str, text: str, k: int) -> list[dict]:
        col = self._collection(key)
        count = col.count()
        if count == 0:
            return []
        embedding = embed_texts([text], kind="query")[0]
        result = col.query(query_embeddings=[embedding], n_results=min(k, count))
        hits = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        dists = result.get("distances", [[]])[0] or [0.0] * len(ids)
        for cid, doc, meta, dist in zip(ids, docs, metas, dists):
            hits.append({"id": cid, "text": doc, "metadata": meta or {}, "distance": dist})
        return hits


def get_store() -> VectorStore:
    global _store, _store_root
    from app.config import get_settings

    root = str(get_settings().data_dir / "stores")
    if _store is None or _store_root != root:
        Path(root).mkdir(parents=True, exist_ok=True)
        _store = VectorStore(Path(root))
        _store_root = root
    return _store


def reset_store() -> None:
    global _store, _store_root
    _store = None
    _store_root = None
