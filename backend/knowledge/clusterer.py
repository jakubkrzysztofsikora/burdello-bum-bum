"""Knowledge atom clustering with cosine agglomerative + c-TF-IDF terms.

Mirrors the lustro cluster_job pipeline: embed atoms, agglomerative
cluster on cosine distance, c-TF-IDF for top terms, mechanical dedup key.
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.knowledge.seeds import resolve_seed_slug
from backend.pipeline.embedding import EmbeddingEngine

logger = logging.getLogger(__name__)


_STOP_TERMS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "into", "when",
    "have", "has", "use", "used", "using", "via", "per", "via", "upon",
    "should", "would", "could", "also", "than", "then", "such", "make",
    "made", "need", "needs", "well", "like", "just", "any", "all",
    "your", "their", "they", "them", "you", "are", "was", "were",
    "will", "can", "may", "not", "but", "its", "out", "over", "more",
    "about", "because", "between", "while", "these", "those", "where",
    "which", "what", "how", "why", "here", "there", "now", "later",
})


@dataclass
class Atom:
    """A single knowledge atom ready for clustering."""

    atom_id: str
    transcript_id: uuid.UUID
    chunk_id: uuid.UUID | None
    project_id: uuid.UUID | None
    name: str
    kind: str
    summary: str
    category_hint: str
    outcome: str | None
    confidence: float
    evidence_type: str = "worked_example"
    embedding: np.ndarray = field(default=None)  # type: ignore[assignment]


@dataclass
class Cluster:
    """A cluster of related atoms."""

    cluster_id: str
    mechanical_key: str
    top_terms: list[str]
    seed_slug: str
    atoms: list[Atom]
    centroid: np.ndarray | None = None


def _slugify_term(term: str) -> str:
    """Lower-case, alphanumeric-only, max 24 chars."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
    return cleaned[:24] or "term"


def _cosine_distance_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Pairwise cosine distance matrix for unit-normalised embeddings."""
    # Embeddings are pre-normalised by EmbeddingEngine; cosine distance
    # = 1 - dot product.
    sims = embeddings @ embeddings.T
    np.clip(sims, -1.0, 1.0, out=sims)
    return 1.0 - sims


def _pick_cluster_count(n: int) -> int:
    """Heuristic cluster target given atom count.

    Args:
        n: Number of atoms.

    Returns:
        Target cluster count (>= 1).
    """
    if n <= 4:
        return 1
    if n <= 12:
        return max(2, n // 4)
    if n <= 50:
        return max(3, int(round(math.sqrt(n))))
    return max(5, min(40, int(round(n ** 0.5))))


def _c_tf_idf_terms(texts: list[str], top_n: int = 8) -> list[str]:
    """Top-N terms for a cluster via class-based TF-IDF (BERTopic style).

    Args:
        texts: Per-atom texts for this cluster (name + summary).
        top_n: Number of terms to return.

    Returns:
        Sorted list of representative terms (most distinctive first).
    """
    if not texts:
        return []
    vec = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
        token_pattern=r"(?u)\b[A-Za-z][A-Za-z0-9_-]{2,}\b",
    )
    try:
        matrix = vec.fit_transform(texts)
    except ValueError:
        return []
    if matrix.shape[1] == 0:
        return []
    scores = matrix.sum(axis=0).A1
    vocab = vec.get_feature_names_out()
    ranked = sorted(
        zip(vocab, scores), key=lambda item: item[1], reverse=True
    )
    terms: list[str] = []
    seen: set[str] = set()
    for term, _score in ranked:
        if term in _STOP_TERMS:
            continue
        if term in seen:
            continue
        terms.append(term)
        seen.add(term)
        if len(terms) >= top_n:
            break
    return terms


def _atom_text(atom: Atom) -> str:
    """Concatenate fields used for embedding + c-TF-IDF."""
    return f"{atom.name}. {atom.summary}"


def embed_atoms(
    atoms: list[Atom], engine: EmbeddingEngine
) -> list[Atom]:
    """Populate ``atom.embedding`` for every atom (in-place).

    Args:
        atoms: Atoms to embed.
        engine: Embedding engine (shared instance).

    Returns:
        The same atom list with embeddings attached.
    """
    if not atoms:
        return atoms
    texts = [_atom_text(a) for a in atoms]
    vectors = engine.embed_batch(texts)
    for atom, vector in zip(atoms, vectors):
        atom.embedding = np.asarray(vector, dtype=np.float32)
    return atoms


def cluster_atoms(
    atoms: list[Atom], distance_threshold: float = 0.35
) -> list[Cluster]:
    """Group atoms into clusters using agglomerative cosine clustering.

    Args:
        atoms: Atoms with embeddings populated.
        distance_threshold: Maximum cosine distance to merge two atoms
            into the same cluster. Lower = more, smaller clusters.

    Returns:
        List of ``Cluster`` records with mechanical_key + top_terms set.
        Returns a single cluster if the input is too small to split.
    """
    if not atoms:
        return []
    if len(atoms) == 1:
        return [_wrap_singleton(atoms[0])]

    matrix = np.stack([a.embedding for a in atoms]).astype(np.float32)
    n_clusters = _pick_cluster_count(len(atoms))
    n_clusters = min(n_clusters, len(atoms))

    model = AgglomerativeClustering(
        n_clusters=n_clusters,
        metric="cosine",
        linkage="average",
    )
    labels = model.fit_predict(matrix)

    grouped: dict[int, list[Atom]] = {}
    for atom, label in zip(atoms, labels):
        grouped.setdefault(int(label), []).append(atom)

    clusters: list[Cluster] = []
    for label, members in grouped.items():
        cluster = _build_cluster(label, members)
        clusters.append(cluster)

    return clusters


def _wrap_singleton(atom: Atom) -> Cluster:
    """Build a single-atom cluster (used when input is too small)."""
    terms = _c_tf_idf_terms([_atom_text(atom)], top_n=4)
    key_parts = [_slugify_term(t) for t in terms[:2]] or ["misc"]
    return Cluster(
        cluster_id=str(uuid.uuid4()),
        mechanical_key=f"atom:{':'.join(key_parts)}",
        top_terms=terms,
        seed_slug=resolve_seed_slug(atom.category_hint),
        atoms=[atom],
    )


def _build_cluster(label: int, members: list[Atom]) -> Cluster:
    """Wrap a labelled group of atoms into a Cluster."""
    texts = [_atom_text(a) for a in members]
    terms = _c_tf_idf_terms(texts, top_n=8)
    key_parts = [_slugify_term(t) for t in terms[:2]] or ["misc"]
    seed_slug = Counter(
        resolve_seed_slug(m.category_hint) for m in members
    ).most_common(1)[0][0]
    centroid = np.mean(
        np.stack([m.embedding for m in members]), axis=0
    )
    return Cluster(
        cluster_id=str(uuid.uuid4()),
        mechanical_key=f"cluster:{':'.join(key_parts)}:{label}",
        top_terms=terms,
        seed_slug=seed_slug,
        atoms=members,
        centroid=centroid,
    )