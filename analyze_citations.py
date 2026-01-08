#!/usr/bin/env python3
"""
Analyze citation data to compute k-cited and k-citing paper lists.

Given a JSON file with citation data for a seed set S of papers, this script computes:
- R_k: papers cited by at least k papers from S (frequently cited references)
- Q_k': papers that cite at least k' papers from S (related work citing the set)

Usage:
    python analyze_citations.py --input citations.json --kcited 2 --kciting 2 \
        --output-cited k_cited.json --output-citing k_citing.json
"""

import argparse
import json
import re
from collections import defaultdict
from typing import Any


def extract_arxiv_id_from_doi(doi: str) -> str | None:
    """Extract arXiv ID from an arXiv DOI (e.g., 10.48550/arXiv.2201.05125 -> 2201.05125)."""
    if not doi:
        return None
    doi_lower = doi.lower()
    # Match patterns like 10.48550/arxiv.XXXX.XXXXX
    match = re.search(r"10\.48550/arxiv\.(\d+\.\d+)", doi_lower)
    if match:
        return match.group(1)
    return None


def normalize_title(title: str) -> str:
    """Normalize a paper title for matching.

    Handles differences in capitalization, whitespace, and common punctuation.
    """
    if not title:
        return ""
    # Lowercase
    normalized = title.lower()
    # Remove extra whitespace
    normalized = " ".join(normalized.split())
    # Remove common punctuation that might differ between versions
    for char in [":", "-", "–", "—", "'", "'", '"', '"', '"']:
        normalized = normalized.replace(char, " ")
    # Collapse multiple spaces again
    normalized = " ".join(normalized.split())
    return normalized.strip()[:150]  # Limit length for key


def get_paper_key(paper: dict) -> str:
    """Generate a unique key for a paper for deduplication.

    Uses normalized title as the primary key to merge papers that have
    different DOIs (e.g., arXiv preprint vs published version).
    Falls back to DOI/arXiv ID if title is not available.
    """
    title = paper.get("title", "")

    # Use normalized title as primary key if available
    if title:
        normalized = normalize_title(title)
        if normalized:
            return f"title:{normalized}"

    # Fallback to DOI/arXiv ID if no title
    doi = paper.get("doi", "")
    arxiv_id = paper.get("arxiv_id", "")

    # Check if DOI is an arXiv DOI and extract the arXiv ID
    arxiv_from_doi = extract_arxiv_id_from_doi(doi)
    if arxiv_from_doi:
        return f"arxiv:{arxiv_from_doi}"

    # Use explicit arXiv ID if available
    if arxiv_id:
        return f"arxiv:{arxiv_id.lower()}"

    # Use DOI for non-arXiv papers
    if doi:
        return f"doi:{doi.lower()}"

    if paper.get("openalex_id"):
        return f"openalex:{paper['openalex_id'].lower()}"
    if paper.get("s2_id"):
        return f"s2:{paper['s2_id'].lower()}"
    return None


def get_seed_paper_label(paper: dict) -> str:
    """Get a readable label for a seed paper."""
    metadata = paper.get("metadata") or {}
    title = metadata.get("title", "Unknown") or "Unknown"
    if len(title) > 60:
        title = title[:57] + "..."
    return title


def analyze_citations(data: dict, k_cited: int, k_citing: int) -> tuple[list, list]:
    """
    Analyze citation data to find:
    - Papers cited by at least k_cited papers from the seed set
    - Papers that cite at least k_citing papers from the seed set

    Returns two lists: (cited_papers, citing_papers)
    """
    papers = data.get("papers", [])

    # Build seed set index (papers in S)
    seed_keys = set()
    seed_by_key = {}
    for paper in papers:
        metadata = paper.get("metadata")
        if metadata:
            key = get_paper_key(metadata)
            if key:
                seed_keys.add(key)
                seed_by_key[key] = {
                    "doi": paper["input_doi"],
                    "title": metadata.get("title", ""),
                    "authors": metadata.get("authors", []),
                    "year": metadata.get("year"),
                }

    # ==========================================================================
    # Compute c_in(r): count how many seed papers cite each reference r
    # ==========================================================================
    # ref_key -> { "metadata": {...}, "cited_by_seed": [list of seed papers] }
    references_index: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"metadata": None, "cited_by_seed": []}
    )

    for paper in papers:
        # Skip papers without metadata
        if not paper.get("metadata"):
            continue

        seed_label = get_seed_paper_label(paper)
        seed_doi = paper.get("input_doi", "")

        for ref in paper.get("references", []):
            ref_key = get_paper_key(ref)
            if not ref_key:
                continue

            # Store/update metadata
            if references_index[ref_key]["metadata"] is None:
                references_index[ref_key]["metadata"] = ref.copy()

            # Record which seed paper cites this reference
            references_index[ref_key]["cited_by_seed"].append(
                {"doi": seed_doi, "title": seed_label}
            )

    # Filter to get R_k: papers cited by at least k_cited seed papers
    # Exclude papers that are already in the seed set
    cited_papers = []
    for ref_key, ref_data in references_index.items():
        # Skip papers that are in the seed set
        if ref_key in seed_keys:
            continue
        c_in = len(ref_data["cited_by_seed"])
        if c_in >= k_cited:
            metadata = ref_data["metadata"]
            cited_papers.append(
                {
                    "key": ref_key,
                    "doi": metadata.get("doi", ""),
                    "arxiv_id": metadata.get("arxiv_id", ""),
                    "title": metadata.get("title", ""),
                    "authors": metadata.get("authors", []),
                    "year": metadata.get("year"),
                    "venue": metadata.get("venue", ""),
                    "c_in": c_in,
                    "cited_by_seed_papers": ref_data["cited_by_seed"],
                    "is_in_seed_set": ref_key in seed_keys,
                }
            )

    # Sort by c_in descending
    cited_papers.sort(key=lambda x: (-x["c_in"], x["title"]))

    # ==========================================================================
    # Compute c_out(q): count how many seed papers each citing paper q cites
    # ==========================================================================
    # citing_key -> { "metadata": {...}, "cites_seed": [list of seed papers] }
    citing_index: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"metadata": None, "cites_seed": []}
    )

    for paper in papers:
        # Skip papers without metadata
        if not paper.get("metadata"):
            continue

        seed_label = get_seed_paper_label(paper)
        seed_doi = paper.get("input_doi", "")

        for citing in paper.get("cited_by", []):
            citing_key = get_paper_key(citing)
            if not citing_key:
                continue

            # Store/update metadata
            if citing_index[citing_key]["metadata"] is None:
                citing_index[citing_key]["metadata"] = citing.copy()

            # Record which seed paper this citing paper cites
            citing_index[citing_key]["cites_seed"].append(
                {"doi": seed_doi, "title": seed_label}
            )

    # Filter to get Q_k': papers citing at least k_citing seed papers
    # Exclude papers that are already in the seed set
    citing_papers = []
    for citing_key, citing_data in citing_index.items():
        # Skip papers that are in the seed set
        if citing_key in seed_keys:
            continue
        c_out = len(citing_data["cites_seed"])
        if c_out >= k_citing:
            metadata = citing_data["metadata"]
            citing_papers.append(
                {
                    "key": citing_key,
                    "doi": metadata.get("doi", ""),
                    "arxiv_id": metadata.get("arxiv_id", ""),
                    "title": metadata.get("title", ""),
                    "authors": metadata.get("authors", []),
                    "year": metadata.get("year"),
                    "venue": metadata.get("venue", ""),
                    "c_out": c_out,
                    "cites_seed_papers": citing_data["cites_seed"],
                    "is_in_seed_set": citing_key in seed_keys,
                }
            )

    # Sort by c_out descending
    citing_papers.sort(key=lambda x: (-x["c_out"], x["title"]))

    return cited_papers, citing_papers


def print_summary(cited_papers: list, citing_papers: list, k_cited: int, k_citing: int):
    """Print a summary of the analysis results."""
    paper_limit = 20
    name_max_length = 100
    print("\n" + "=" * 70)
    print("ANALYSIS SUMMARY")
    print("=" * 70)

    print(
        f"\n📚 Papers CITED by at least {k_cited} seed papers (R_k): {len(cited_papers)}"
    )
    if cited_papers:
        print("-" * 70)
        for i, p in enumerate(cited_papers[:paper_limit], 1):
            title = (
                p["title"][:name_max_length] + "..."
                if len(p["title"]) > name_max_length
                else p["title"]
            )
            print(f"  {i:2}. [c_in={p['c_in']}] {title}")
            print(
                f"      Year: {p['year']} | {'DOI: ' + p['doi'] if p['doi'] else 'arXiv: ' + p['arxiv_id'] if p['arxiv_id'] else 'No ID'}"
            )
        if len(cited_papers) > paper_limit:
            print(f"  ... and {len(cited_papers) - paper_limit} more")

    print(
        f"\n📖 Papers CITING at least {k_citing} seed papers (Q_k'): {len(citing_papers)}"
    )
    if citing_papers:
        print("-" * 70)
        for i, p in enumerate(citing_papers[:paper_limit], 1):
            title = (
                p["title"][:name_max_length] + "..."
                if len(p["title"]) > name_max_length
                else p["title"]
            )
            print(f"  {i:2}. [c_out={p['c_out']}] {title}")
            print(
                f"      Year: {p['year']} | {'DOI: ' + p['doi'] if p['doi'] else 'arXiv: ' + p['arxiv_id'] if p['arxiv_id'] else 'No ID'}"
            )
        if len(citing_papers) > paper_limit:
            print(f"  ... and {len(citing_papers) - paper_limit} more")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze citation data to compute k-cited and k-citing paper lists"
    )
    parser.add_argument(
        "--input", "-i", required=True, help="Input JSON file from get_citations.py"
    )
    parser.add_argument(
        "--kcited",
        type=int,
        default=2,
        help="Minimum number of seed papers that must cite a reference (default: 2)",
    )
    parser.add_argument(
        "--kciting",
        type=int,
        default=2,
        help="Minimum number of seed papers that a citing paper must cite (default: 2)",
    )
    parser.add_argument(
        "--output-cited",
        default="k_cited.json",
        help="Output JSON file for frequently cited papers (default: k_cited.json)",
    )
    parser.add_argument(
        "--output-citing",
        default="k_citing.json",
        help="Output JSON file for papers citing multiple seeds (default: k_citing.json)",
    )

    args = parser.parse_args()

    # Load citation data
    print(f"Loading citation data from: {args.input}")
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    num_seed_papers = len(data.get("papers", []))
    print(f"Seed set contains {num_seed_papers} papers")

    # Analyze
    print(
        f"Computing R_k (k_cited >= {args.kcited}) and Q_k' (k_citing >= {args.kciting})..."
    )
    cited_papers, citing_papers = analyze_citations(data, args.kcited, args.kciting)

    # Save results
    cited_output = {
        "description": f"Papers cited by at least {args.kcited} papers from the seed set",
        "k_cited": args.kcited,
        "count": len(cited_papers),
        "papers": cited_papers,
    }

    citing_output = {
        "description": f"Papers citing at least {args.kciting} papers from the seed set",
        "k_citing": args.kciting,
        "count": len(citing_papers),
        "papers": citing_papers,
    }

    with open(args.output_cited, "w", encoding="utf-8") as f:
        json.dump(cited_output, f, indent=2, ensure_ascii=False)
    print(f"Saved cited papers to: {args.output_cited}")

    with open(args.output_citing, "w", encoding="utf-8") as f:
        json.dump(citing_output, f, indent=2, ensure_ascii=False)
    print(f"Saved citing papers to: {args.output_citing}")

    # Print summary
    print_summary(cited_papers, citing_papers, args.kcited, args.kciting)


if __name__ == "__main__":
    main()
