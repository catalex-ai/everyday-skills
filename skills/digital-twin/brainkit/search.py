"""Hybrid search over a facts list: FTS5 BM25 plus model2vec cosine, fused with RRF.

Pure over a list of dicts with id, about and text. No store, raw or policy imports.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

import numpy as np

RRF_K = 60
CANDIDATES = 50
_MODEL_UNSET = object()
_model = _MODEL_UNSET


def _load_model():
    """Load the embedder once. Returns None if unavailable."""
    global _model
    if _model is _MODEL_UNSET:
        try:
            from model2vec import StaticModel

            name = os.environ.get("TWIN_EMBED_MODEL", "minishlab/potion-base-8M")
            _model = StaticModel.from_pretrained(name)
        except Exception:
            _model = None
    return _model


def embedder_available() -> bool:
    return _load_model() is not None


def _embed(texts: list[str]) -> np.ndarray | None:
    model = _load_model()
    if model is None:
        return None
    vecs = np.asarray(model.encode(texts), dtype=np.float32)
    if vecs.ndim == 1:
        vecs = vecs.reshape(1, -1)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def _fts_query(q: str) -> str:
    tokens = re.findall(r"\w+", q or "", re.UNICODE)
    return " OR ".join('"%s"' % t for t in tokens)


def _atomic(path: Path, writer) -> None:
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    writer(tmp)
    os.replace(tmp, path)


def build_index(persona_dir: Path, facts: list[dict]) -> None:
    persona_dir = Path(persona_dir)
    persona_dir.mkdir(parents=True, exist_ok=True)

    def write_db(tmp: Path) -> None:
        con = sqlite3.connect(tmp)
        try:
            con.execute(
                "CREATE VIRTUAL TABLE facts USING fts5("
                "id UNINDEXED, about, text, tokenize='porter unicode61')"
            )
            con.executemany(
                "INSERT INTO facts(id, about, text) VALUES (?,?,?)",
                [(f["id"], f.get("about", "me"), f["text"]) for f in facts],
            )
            con.commit()
        finally:
            con.close()

    _atomic(persona_dir / "index.sqlite", write_db)

    vec_path = persona_dir / "vectors.npy"
    ids_path = persona_dir / "vec_ids.json"
    vecs = _embed([f["text"] for f in facts]) if facts else None
    if vecs is None:
        for p in (vec_path, ids_path):
            if p.exists():
                p.unlink()
        return

    def write_vecs(tmp: Path) -> None:
        with open(tmp, "wb") as fh:
            np.save(fh, vecs.astype(np.float32))

    def write_ids(tmp: Path) -> None:
        tmp.write_text(json.dumps([f["id"] for f in facts]), encoding="utf-8")

    _atomic(vec_path, write_vecs)
    _atomic(ids_path, write_ids)


class Index:
    def __init__(self, con: sqlite3.Connection, vectors, vec_ids):
        self._con = con
        self._vectors = vectors
        self._vec_ids = vec_ids

    def _bm25(self, q: str) -> list[tuple[str, str, str]]:
        expr = _fts_query(q)
        if not expr:
            return []
        try:
            return self._con.execute(
                "SELECT id, about, text FROM facts WHERE facts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (expr, CANDIDATES),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    def _dense(self, q: str) -> list[str]:
        if self._vectors is None or not self._vec_ids:
            return []
        qv = _embed([q])
        if qv is None:
            return []
        sims = self._vectors @ qv[0]
        order = np.argsort(-sims)[:CANDIDATES]
        return [self._vec_ids[i] for i in order]

    def search(self, q: str, k: int = 8) -> list[dict]:
        if not _fts_query(q):
            return []
        rows = {r[0]: r for r in self._bm25(q)}
        bm_ids = list(rows)
        dense_ids = self._dense(q)
        scores: dict[str, float] = {}
        for ranking in (bm_ids, dense_ids):
            for rank, fid in enumerate(ranking):
                scores[fid] = scores.get(fid, 0.0) + 1.0 / (RRF_K + rank + 1)
        top = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        missing = [fid for fid, _ in top if fid not in rows]
        for fid in missing:
            r = self._con.execute(
                "SELECT id, about, text FROM facts WHERE id = ?", (fid,)
            ).fetchone()
            if r:
                rows[fid] = r
        return [
            {"id": fid, "about": rows[fid][1], "text": rows[fid][2], "score": s}
            for fid, s in top
            if fid in rows
        ]

    def close(self) -> None:
        self._con.close()


def open_ro(persona_dir: Path) -> Index:
    persona_dir = Path(persona_dir)
    uri = "file:%s?mode=ro" % (persona_dir / "index.sqlite").resolve().as_posix()
    con = sqlite3.connect(uri, uri=True)
    vectors = vec_ids = None
    vp, ip = persona_dir / "vectors.npy", persona_dir / "vec_ids.json"
    if vp.exists() and ip.exists() and embedder_available():
        try:
            vectors = np.load(vp)
            vec_ids = json.loads(ip.read_text(encoding="utf-8"))
        except Exception:
            vectors = vec_ids = None
    return Index(con, vectors, vec_ids)
