"""Port binding and the lightweight embedding default used on small hosts."""

from app.config import get_settings
from app.stores.embeddings import embed_texts, hash_embed


def test_port_falls_back_to_7860(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert get_settings().port == 7860


def test_port_follows_the_environment(monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    assert get_settings().port == 10000


def test_hash_embeddings_skip_the_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    vectors = embed_texts(["shell design pressure 18 barg"], kind="query")
    assert len(vectors) == 1
    assert len(vectors[0]) == len(hash_embed("shell design pressure 18 barg"))
