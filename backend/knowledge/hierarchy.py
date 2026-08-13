"""Hierarchy assembly: attach clusters under seed roots + RAPTOR linkage."""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

from backend.knowledge.clusterer import Atom, Cluster
from backend.knowledge.seeds import CATEGORY_SEEDS, CategorySeed

logger = logging.getLogger(__name__)


@dataclass
class HierNode:
    """A node ready for insertion into the KB tree."""

    slug: str
    title: str
    node_type: str
    parent_slug: str | None
    summary_seed: str
    seed_slug: str | None
    mechanical_key: str
    top_terms: list[str]
    confidence: float
    atoms: list[Atom] = field(default_factory=list)
    children: list["HierNode"] = field(default_factory=list)


def _group_by_seed(clusters: list[Cluster]) -> dict[str, list[Cluster]]:
    """Partition clusters by their resolved seed slug."""
    grouped: dict[str, list[Cluster]] = defaultdict(list)
    for cluster in clusters:
        grouped[cluster.seed_slug].append(cluster)
    return dict(grouped)


def _linkage_children(
    clusters: list[Cluster], distance_threshold: float = 0.4
) -> list[list[Cluster]]:
    """Group clusters inside one root into 2-4 sibling groups.

    Args:
        clusters: Clusters sharing the same seed slug.
        distance_threshold: Cosine distance threshold for the linkage
            cut. Lower = more, smaller groups.

    Returns:
        List of sibling groups (each becomes a subcategory node).
    """
    if len(clusters) <= 2:
        return [clusters]
    matrix = np.stack([c.centroid for c in clusters]).astype(np.float32)
    z = linkage(matrix, method="average", metric="cosine")
    labels = fcluster(z, t=distance_threshold, criterion="distance")
    groups: dict[int, list[Cluster]] = defaultdict(list)
    for cluster, label in zip(clusters, labels):
        groups[int(label)].append(cluster)
    return list(groups.values())


def build_hierarchy(clusters: list[Cluster]) -> list[HierNode]:
    """Build a tree of ``HierNode`` records ready for KbNode insertion.

    Layout:

    - 10 root ``HierNode`` records (one per seed).
    - For each root, 1+ subcategory ``HierNode`` records produced by
      scipy linkage over the clusters assigned to that root.
    - Leaf ``HierNode`` records, one per original cluster, parented to
      their subcategory (or directly to the root when the root has no
      subcategories).

    Args:
        clusters: Output of ``cluster_atoms``.

    Returns:
        Flat list of ``HierNode`` records. Parent links reference nodes
        by ``slug``; consumers resolve them when persisting.
    """
    seed_lookup = {seed.slug: seed for seed in CATEGORY_SEEDS}
    grouped = _group_by_seed(clusters)

    out: list[HierNode] = []

    for seed in CATEGORY_SEEDS:
        seed_clusters = grouped.get(seed.slug, [])
        root_node = HierNode(
            slug=seed.slug,
            title=seed.title,
            node_type="category",
            parent_slug=None,
            summary_seed=seed.summary,
            seed_slug=seed.slug,
            mechanical_key=f"root:{seed.slug}",
            top_terms=[],
            confidence=1.0,
        )
        out.append(root_node)

        if not seed_clusters:
            continue

        sibling_groups = _linkage_children(seed_clusters)

        for sub_idx, sibling_clusters in enumerate(sibling_groups):
            sub_slug = (
                f"{seed.slug}-sub-{sub_idx + 1}"
                if len(sibling_groups) > 1
                else f"{seed.slug}-topics"
            )
            sub_node = HierNode(
                slug=sub_slug,
                title=_subcategory_title(sibling_clusters),
                node_type="subcategory",
                parent_slug=root_node.slug,
                summary_seed="",
                seed_slug=seed.slug,
                mechanical_key=f"sub:{seed.slug}:{sub_idx}",
                top_terms=_merge_terms(sibling_clusters),
                confidence=_avg_confidence(sibling_clusters),
            )
            out.append(sub_node)

            for cluster in sibling_clusters:
                leaf_slug = _content_slug(seed.slug, cluster)
                leaf_node = HierNode(
                    slug=leaf_slug,
                    title=_cluster_title(cluster),
                    node_type="topic",
                    parent_slug=sub_node.slug,
                    summary_seed="",
                    seed_slug=seed.slug,
                    mechanical_key=cluster.mechanical_key,
                    top_terms=cluster.top_terms,
                    confidence=_avg_confidence([cluster]),
                    atoms=list(cluster.atoms),
                )
                out.append(leaf_node)

    return out


def _subcategory_title(clusters: list[Cluster]) -> str:
    """Best-effort title for a subcategory from its clusters' top terms."""
    terms = _merge_terms(clusters)[:3]
    return " · ".join(t.title() for t in terms) or "Topics"


def _cluster_title(cluster: Cluster) -> str:
    """Best-effort title for a leaf cluster from its top terms."""
    if cluster.atoms:
        first = cluster.atoms[0].name.strip()
        if first:
            return first[:120]
    terms = cluster.top_terms[:3]
    return " · ".join(t.title() for t in terms) or "Cluster"


def _merge_terms(clusters: list[Cluster]) -> list[str]:
    """Flatten + dedup terms across multiple clusters."""
    seen: set[str] = set()
    out: list[str] = []
    for cluster in clusters:
        for term in cluster.top_terms:
            if term in seen:
                continue
            seen.add(term)
            out.append(term)
    return out


def _avg_confidence(clusters: list[Cluster]) -> float:
    total = sum(a.confidence for c in clusters for a in c.atoms)
    n = sum(len(c.atoms) for c in clusters)
    return float(total / n) if n else 0.0


def _content_slug(seed_slug: str, cluster: Cluster) -> str:
    """Deterministic leaf slug from cluster content.

    Slug = ``{seed_slug}-{first_two_terms_joined}-{6char_hash}``. Hash suffix
    disambiguates clusters that share the same top terms but differ in the
    long tail, so re-runs produce the same slug for the same atoms.

    Args:
        seed_slug: Root category slug.
        cluster: Cluster whose top terms + atoms seed the slug.

    Returns:
        Stable, URL-safe slug string.
    """
    terms = [
        re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
        for t in cluster.top_terms[:2]
    ]
    terms = [t[:16] for t in terms if t] or ["topic"]
    joined = "-".join(terms)
    digest = hashlib.sha256(
        (cluster.mechanical_key + "|" + seed_slug).encode()
    ).hexdigest()[:6]
    return f"{seed_slug}-{joined}-{digest}"