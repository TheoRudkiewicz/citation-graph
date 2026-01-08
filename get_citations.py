#!/usr/bin/env python3
"""
Fetch paper metadata and citations from OpenAlex and Semantic Scholar APIs.

Uses both sources and merges results for better coverage, especially for arXiv papers.

Usage:
    python get_citations.py --input doi_list.txt --output citations.json
"""

import argparse
import json
import time
from typing import Optional
from urllib.parse import quote

import requests


# OpenAlex configuration
OPENALEX_BASE_URL = "https://api.openalex.org"
OPENALEX_HEADERS = {"User-Agent": "CitationGetter/1.0 (mailto:your-email@example.com)"}

# Semantic Scholar configuration
S2_BASE_URL = "https://api.semanticscholar.org/graph/v1"
S2_HEADERS = {}  # Add "x-api-key": "YOUR_KEY" for higher rate limits

# Rate limiting: be polite to the APIs
REQUEST_DELAY = 5.0  # seconds between requests (S2 free tier is rate-limited)
# Max API calls 100 per 5 minutes for S2 free tier


def normalize_doi(doi: str) -> str:
    """Normalize DOI to bare format (without URL prefix)."""
    doi = doi.strip()
    prefixes = ["https://doi.org/", "http://doi.org/", "doi:"]
    for prefix in prefixes:
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix) :]
            break
    return doi


def extract_arxiv_id(doi: str) -> Optional[str]:
    """Extract arXiv ID from a DOI if it's an arXiv paper."""
    normalized = normalize_doi(doi)
    if "arxiv" in normalized.lower():
        # Format: 10.48550/arXiv.XXXX.XXXXX
        parts = normalized.split("arXiv.")
        if len(parts) > 1:
            return parts[1]
    return None


# =============================================================================
# OpenAlex API functions
# =============================================================================


def openalex_get_work_by_doi(doi: str) -> Optional[dict]:
    """Fetch a work from OpenAlex by DOI."""
    normalized_doi = normalize_doi(doi)
    url = f"{OPENALEX_BASE_URL}/works/https://doi.org/{quote(normalized_doi, safe='')}"

    try:
        response = requests.get(url, headers=OPENALEX_HEADERS, timeout=30)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print(f"    [OpenAlex] DOI not found: {doi}")
            return None
        else:
            print(f"    [OpenAlex] API error {response.status_code}")
            return None
    except requests.RequestException as e:
        print(f"    [OpenAlex] Request failed: {e}")
        return None


def openalex_get_references(work: dict) -> list[dict]:
    """Get papers that this work cites from OpenAlex."""
    referenced_work_ids = work.get("referenced_works", [])

    if not referenced_work_ids:
        return []

    references = []
    batch_size = 50
    for i in range(0, len(referenced_work_ids), batch_size):
        batch_ids = referenced_work_ids[i : i + batch_size]
        ids_filter = "|".join(batch_ids)
        url = f"{OPENALEX_BASE_URL}/works?filter=openalex:{ids_filter}&per-page={batch_size}"

        try:
            response = requests.get(url, headers=OPENALEX_HEADERS, timeout=30)
            if response.status_code == 200:
                data = response.json()
                references.extend(data.get("results", []))
            time.sleep(REQUEST_DELAY)
        except requests.RequestException as e:
            print(f"    [OpenAlex] Failed to fetch references batch: {e}")

    return references


def openalex_get_citing_works(work: dict, max_results: int = 500) -> list[dict]:
    """Get papers that cite this work from OpenAlex."""
    work_id = work.get("id", "")
    if not work_id:
        return []

    citing_works = []
    cursor = "*"

    while cursor and len(citing_works) < max_results:
        url = f"{OPENALEX_BASE_URL}/works?filter=cites:{work_id}&per-page=100&cursor={cursor}"

        try:
            response = requests.get(url, headers=OPENALEX_HEADERS, timeout=30)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                citing_works.extend(results)
                meta = data.get("meta", {})
                cursor = meta.get("next_cursor")
                if not results:
                    break
            else:
                break
            time.sleep(REQUEST_DELAY)
        except requests.RequestException as e:
            print(f"    [OpenAlex] Failed to fetch citing works: {e}")
            break

    return citing_works[:max_results]


def openalex_extract_metadata(work: dict) -> dict:
    """Extract metadata from an OpenAlex work object."""
    authors = []
    for authorship in work.get("authorships", []):
        author = authorship.get("author", {})
        if author.get("display_name"):
            authors.append(author["display_name"])

    primary_location = work.get("primary_location", {}) or {}
    source = primary_location.get("source", {}) or {}
    venue = source.get("display_name", "")

    doi = work.get("doi", "")
    if doi and doi.startswith("https://doi.org/"):
        doi = doi[16:]

    return {
        "openalex_id": work.get("id", ""),
        "doi": doi,
        "title": work.get("title", ""),
        "authors": authors,
        "year": work.get("publication_year"),
        "venue": venue,
        "type": work.get("type", ""),
        "cited_by_count": work.get("cited_by_count", 0),
        "source": "openalex",
    }


# =============================================================================
# Semantic Scholar API functions
# =============================================================================


def s2_get_paper(doi: str) -> Optional[dict]:
    """Fetch a paper from Semantic Scholar by DOI or arXiv ID."""
    # Try arXiv ID first (better coverage for preprints)
    arxiv_id = extract_arxiv_id(doi)
    if arxiv_id:
        url = f"{S2_BASE_URL}/paper/arXiv:{arxiv_id}"
    else:
        normalized_doi = normalize_doi(doi)
        url = f"{S2_BASE_URL}/paper/DOI:{normalized_doi}"

    fields = "paperId,externalIds,title,authors,year,venue,citationCount,referenceCount"

    try:
        response = requests.get(f"{url}?fields={fields}", headers=S2_HEADERS, timeout=30)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print(f"    [S2] Paper not found")
            return None
        else:
            print(f"    [S2] API error {response.status_code}")
            return None
    except requests.RequestException as e:
        print(f"    [S2] Request failed: {e}")
        return None


def s2_get_references(paper_id: str, max_results: int = 500) -> list[dict]:
    """Get papers that this paper cites from Semantic Scholar."""
    url = f"{S2_BASE_URL}/paper/{paper_id}/references"
    fields = "paperId,externalIds,title,authors,year,venue,citationCount"

    references = []
    offset = 0
    limit = 100

    while offset < max_results:
        try:
            response = requests.get(
                f"{url}?fields={fields}&offset={offset}&limit={limit}",
                headers=S2_HEADERS,
                timeout=30,
            )
            if response.status_code == 200:
                data = response.json()
                batch = data.get("data", [])
                if not batch:
                    break
                references.extend(batch)
                offset += limit
            else:
                break
            time.sleep(REQUEST_DELAY)
        except requests.RequestException as e:
            print(f"    [S2] Failed to fetch references: {e}")
            break

    return references[:max_results]


def s2_get_citations(paper_id: str, max_results: int = 500) -> list[dict]:
    """Get papers that cite this paper from Semantic Scholar."""
    url = f"{S2_BASE_URL}/paper/{paper_id}/citations"
    fields = "paperId,externalIds,title,authors,year,venue,citationCount"

    citations = []
    offset = 0
    limit = 100

    while offset < max_results:
        try:
            response = requests.get(
                f"{url}?fields={fields}&offset={offset}&limit={limit}",
                headers=S2_HEADERS,
                timeout=30,
            )
            if response.status_code == 200:
                data = response.json()
                batch = data.get("data", [])
                if not batch:
                    break
                citations.extend(batch)
                offset += limit
            else:
                break
            time.sleep(REQUEST_DELAY)
        except requests.RequestException as e:
            print(f"    [S2] Failed to fetch citations: {e}")
            break

    return citations[:max_results]


def s2_extract_metadata(paper: dict) -> dict:
    """Extract metadata from a Semantic Scholar paper object."""
    # Handle nested structure from references/citations endpoints
    if "citingPaper" in paper:
        paper = paper["citingPaper"]
    elif "citedPaper" in paper:
        paper = paper["citedPaper"]

    if not paper:
        return None

    authors = [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]

    external_ids = paper.get("externalIds", {}) or {}
    doi = external_ids.get("DOI", "")
    arxiv_id = external_ids.get("ArXiv", "")

    return {
        "s2_id": paper.get("paperId", ""),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "title": paper.get("title", ""),
        "authors": authors,
        "year": paper.get("year"),
        "venue": paper.get("venue", ""),
        "cited_by_count": paper.get("citationCount", 0),
        "source": "semantic_scholar",
    }


# =============================================================================
# Merging and deduplication
# =============================================================================


def get_paper_key(paper: dict) -> str:
    """Generate a unique key for a paper for deduplication."""
    # Prefer DOI, then arXiv ID, then title-based key
    if paper.get("doi"):
        return f"doi:{paper['doi'].lower()}"
    if paper.get("arxiv_id"):
        return f"arxiv:{paper['arxiv_id'].lower()}"
    if paper.get("title"):
        # Normalize title for matching
        return f"title:{paper['title'].lower()[:100]}"
    return f"unknown:{id(paper)}"


def merge_paper_lists(list1: list[dict], list2: list[dict]) -> list[dict]:
    """Merge two lists of papers, removing duplicates."""
    seen = {}

    for paper in list1 + list2:
        if paper is None:
            continue
        key = get_paper_key(paper)
        if key not in seen:
            seen[key] = paper
        else:
            # Merge metadata: prefer non-empty values
            existing = seen[key]
            for field in ["doi", "arxiv_id", "title", "authors", "year", "venue"]:
                if not existing.get(field) and paper.get(field):
                    existing[field] = paper[field]
            # Combine source info
            if existing.get("source") != paper.get("source"):
                existing["source"] = "openalex+semantic_scholar"

    return list(seen.values())


def process_doi(doi: str, max_citing: int = 500) -> dict:
    """
    Process a single DOI: fetch metadata, references, and citing works from both APIs.

    Returns a dictionary with merged information from OpenAlex and Semantic Scholar.
    """
    result = {
        "input_doi": doi,
        "metadata": None,
        "references": [],
        "cited_by": [],
        "sources_used": [],
        "error": None,
    }

    # ==========================================================================
    # Fetch from OpenAlex
    # ==========================================================================
    print(f"  Querying OpenAlex...")
    oa_work = openalex_get_work_by_doi(doi)
    oa_references = []
    oa_citing = []

    if oa_work:
        result["sources_used"].append("openalex")
        result["metadata"] = openalex_extract_metadata(oa_work)

        oa_references_raw = openalex_get_references(oa_work)
        oa_references = [openalex_extract_metadata(r) for r in oa_references_raw]
        print(f"    [OpenAlex] Found {len(oa_references)} references")

        oa_citing_raw = openalex_get_citing_works(oa_work, max_citing)
        oa_citing = [openalex_extract_metadata(c) for c in oa_citing_raw]
        print(f"    [OpenAlex] Found {len(oa_citing)} citing works")

    time.sleep(REQUEST_DELAY)

    # ==========================================================================
    # Fetch from Semantic Scholar
    # ==========================================================================
    print(f"  Querying Semantic Scholar...")
    s2_paper = s2_get_paper(doi)
    s2_references = []
    s2_citing = []

    if s2_paper:
        result["sources_used"].append("semantic_scholar")
        paper_id = s2_paper.get("paperId")

        # Use S2 metadata if OpenAlex didn't find it
        if result["metadata"] is None:
            result["metadata"] = s2_extract_metadata(s2_paper)

        if paper_id:
            s2_refs_raw = s2_get_references(paper_id, max_citing)
            s2_references = [s2_extract_metadata(r) for r in s2_refs_raw if r]
            s2_references = [r for r in s2_references if r is not None]
            print(f"    [S2] Found {len(s2_references)} references")

            s2_citing_raw = s2_get_citations(paper_id, max_citing)
            s2_citing = [s2_extract_metadata(c) for c in s2_citing_raw if c]
            s2_citing = [c for c in s2_citing if c is not None]
            print(f"    [S2] Found {len(s2_citing)} citing works")

    # ==========================================================================
    # Merge results
    # ==========================================================================
    result["references"] = merge_paper_lists(oa_references, s2_references)
    result["cited_by"] = merge_paper_lists(oa_citing, s2_citing)

    print(
        f"  Total: {len(result['references'])} references, {len(result['cited_by'])} citing works"
    )

    if not result["metadata"]:
        result["error"] = "Paper not found in any source"

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Fetch paper metadata and citations from OpenAlex and Semantic Scholar APIs"
    )
    parser.add_argument(
        "--input", "-i", required=True, help="Input file containing DOIs (one per line)"
    )
    parser.add_argument("--output", "-o", required=True, help="Output JSON file")
    parser.add_argument(
        "--max-citing",
        type=int,
        default=500,
        help="Maximum number of citing works to fetch per paper (default: 500)",
    )

    args = parser.parse_args()

    # Read DOIs from input file
    with open(args.input, "r", encoding="utf-8") as f:
        dois = [line.strip() for line in f if line.strip()]

    print(f"Processing {len(dois)} DOIs using OpenAlex + Semantic Scholar...")

    results = []
    for i, doi in enumerate(dois, 1):
        print(f"\n[{i}/{len(dois)}] Processing: {doi}")
        result = process_doi(doi, args.max_citing)
        results.append(result)
        time.sleep(REQUEST_DELAY)

    # Write output
    output_data = {
        "query_info": {
            "input_file": args.input,
            "num_dois": len(dois),
            "max_citing_per_paper": args.max_citing,
            "sources": ["openalex", "semantic_scholar"],
        },
        "papers": results,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to: {args.output}")

    # Print summary
    successful = sum(1 for r in results if r["error"] is None)
    total_refs = sum(len(r["references"]) for r in results)
    total_citing = sum(len(r["cited_by"]) for r in results)
    print(f"Successfully processed: {successful}/{len(dois)} papers")
    print(f"Total references found: {total_refs}")
    print(f"Total citing works found: {total_citing}")


if __name__ == "__main__":
    main()
