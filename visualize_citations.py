#!/usr/bin/env python3
"""
Visualize citation relationships as an interactive graph.

Creates an HTML visualization showing:
- Seed papers (S)
- Papers cited by at least k_cited seed papers (R_k)
- Papers citing at least k_citing seed papers (Q_k')

Usage:
    python visualize_citations.py --input citations.json --kcited 2 --kciting 2 --output graph.html
"""

import argparse
import json
from collections import defaultdict
from typing import Any

try:
    from pyvis.network import Network
except ImportError:
    print("Error: pyvis is required. Install it with: pip install pyvis")
    exit(1)


def get_paper_key(paper: dict) -> str:
    """Generate a unique key for a paper for deduplication."""
    if paper.get("doi"):
        return f"doi:{paper['doi'].lower()}"
    if paper.get("arxiv_id"):
        return f"arxiv:{paper['arxiv_id'].lower()}"
    if paper.get("openalex_id"):
        return f"openalex:{paper['openalex_id'].lower()}"
    if paper.get("s2_id"):
        return f"s2:{paper['s2_id'].lower()}"
    if paper.get("title"):
        return f"title:{paper['title'].lower()[:100]}"
    return None


def truncate_title(title: str, max_len: int = 40) -> str:
    """Truncate title for display."""
    if not title:
        return "Unknown"
    if len(title) <= max_len:
        return title
    return title[: max_len - 3] + "..."


def analyze_for_graph(data: dict, k_cited: int, k_citing: int) -> dict:
    """
    Analyze citation data and prepare graph data.

    Returns a dict with nodes and edges for visualization.
    """
    papers = data.get("papers", [])

    # Build seed set
    seed_papers = {}
    for paper in papers:
        if paper.get("metadata"):
            key = get_paper_key(paper["metadata"])
            if key:
                seed_papers[key] = {
                    "key": key,
                    "doi": paper["input_doi"],
                    "title": paper["metadata"].get("title", "Unknown"),
                    "authors": paper["metadata"].get("authors", []),
                    "year": paper["metadata"].get("year"),
                    "venue": paper["metadata"].get("venue", ""),
                }

    # Count references (c_in)
    references_index: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"metadata": None, "cited_by_seed": set()}
    )

    # Count citing papers (c_out)
    citing_index: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"metadata": None, "cites_seed": set()}
    )

    # Build edges
    edges = []  # (source_key, target_key, edge_type)

    for paper in papers:
        seed_key = get_paper_key(paper["metadata"]) if paper.get("metadata") else None
        if not seed_key:
            continue

        # Process references (seed -> reference)
        for ref in paper.get("references", []):
            ref_key = get_paper_key(ref)
            if not ref_key:
                continue

            if references_index[ref_key]["metadata"] is None:
                references_index[ref_key]["metadata"] = ref.copy()

            references_index[ref_key]["cited_by_seed"].add(seed_key)
            edges.append((seed_key, ref_key, "cites"))

        # Process citing papers (citing -> seed)
        for citing in paper.get("cited_by", []):
            citing_key = get_paper_key(citing)
            if not citing_key:
                continue

            if citing_index[citing_key]["metadata"] is None:
                citing_index[citing_key]["metadata"] = citing.copy()

            citing_index[citing_key]["cites_seed"].add(seed_key)
            edges.append((citing_key, seed_key, "cites"))

    # Filter by thresholds
    cited_papers = {}  # R_k
    for ref_key, ref_data in references_index.items():
        c_in = len(ref_data["cited_by_seed"])
        if c_in >= k_cited and ref_key not in seed_papers:
            metadata = ref_data["metadata"]
            cited_papers[ref_key] = {
                "key": ref_key,
                "title": metadata.get("title", "Unknown"),
                "authors": metadata.get("authors", []),
                "year": metadata.get("year"),
                "venue": metadata.get("venue", ""),
                "c_in": c_in,
            }

    citing_papers = {}  # Q_k'
    for citing_key, citing_data in citing_index.items():
        c_out = len(citing_data["cites_seed"])
        if c_out >= k_citing and citing_key not in seed_papers:
            metadata = citing_data["metadata"]
            citing_papers[citing_key] = {
                "key": citing_key,
                "title": metadata.get("title", "Unknown"),
                "authors": metadata.get("authors", []),
                "year": metadata.get("year"),
                "venue": metadata.get("venue", ""),
                "c_out": c_out,
            }

    # Filter edges to only include relevant nodes
    all_relevant_keys = (
        set(seed_papers.keys()) | set(cited_papers.keys()) | set(citing_papers.keys())
    )
    filtered_edges = [
        (src, tgt, etype)
        for src, tgt, etype in edges
        if src in all_relevant_keys and tgt in all_relevant_keys
    ]

    # Deduplicate edges
    unique_edges = list(set(filtered_edges))

    return {
        "seed_papers": seed_papers,
        "cited_papers": cited_papers,
        "citing_papers": citing_papers,
        "edges": unique_edges,
    }


def create_visualization(graph_data: dict, output_path: str, k_cited: int, k_citing: int):
    """Create an interactive HTML visualization using pyvis."""

    # Initialize network
    net = Network(
        height="800px",
        width="100%",
        bgcolor="#ffffff",
        font_color="#333333",
        directed=True,
        notebook=False,
    )

    # Physics settings for better layout
    net.set_options("""
    {
        "nodes": {
            "font": {
                "size": 14,
                "face": "arial"
            }
        },
        "edges": {
            "arrows": {
                "to": {
                    "enabled": true,
                    "scaleFactor": 0.5
                }
            },
            "color": {
                "color": "#cccccc",
                "highlight": "#666666"
            },
            "smooth": {
                "type": "continuous",
                "forceDirection": "none"
            }
        },
        "physics": {
            "enabled": true,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
                "gravitationalConstant": -100,
                "centralGravity": 0.01,
                "springLength": 150,
                "springConstant": 0.08
            },
            "stabilization": {
                "iterations": 200
            }
        },
        "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "navigationButtons": true,
            "keyboard": true
        }
    }
    """)

    # Color scheme
    SEED_COLOR = "#4CAF50"  # Green for seed papers
    CITED_COLOR = "#2196F3"  # Blue for cited papers (references)
    CITING_COLOR = "#FF9800"  # Orange for citing papers

    # Add seed paper nodes (square shape)
    for key, paper in graph_data["seed_papers"].items():
        label = truncate_title(paper["title"], 30)
        title_html = f"""
        <b>SEED PAPER</b><br>
        <b>{paper["title"]}</b><br>
        Year: {paper["year"]}<br>
        Authors: {", ".join(paper["authors"][:3])}{"..." if len(paper["authors"]) > 3 else ""}<br>
        Venue: {paper["venue"]}
        """
        net.add_node(
            key,
            label=label,
            title=title_html,
            color=SEED_COLOR,
            shape="square",
            size=30,
            borderWidth=3,
        )

    # Add cited paper nodes (R_k) - circle shape
    for key, paper in graph_data["cited_papers"].items():
        label = truncate_title(paper["title"], 30)
        title_html = f"""
        <b>CITED PAPER (c_in={paper["c_in"]})</b><br>
        <b>{paper["title"]}</b><br>
        Year: {paper["year"]}<br>
        Authors: {", ".join(paper["authors"][:3])}{"..." if len(paper["authors"]) > 3 else ""}<br>
        Venue: {paper["venue"]}
        """
        # Size based on c_in
        size = 15 + paper["c_in"] * 5
        net.add_node(
            key,
            label=label,
            title=title_html,
            color=CITED_COLOR,
            shape="dot",
            size=size,
            borderWidth=2,
        )

    # Add citing paper nodes (Q_k') - triangle shape
    for key, paper in graph_data["citing_papers"].items():
        label = truncate_title(paper["title"], 30)
        title_html = f"""
        <b>CITING PAPER (c_out={paper["c_out"]})</b><br>
        <b>{paper["title"]}</b><br>
        Year: {paper["year"]}<br>
        Authors: {", ".join(paper["authors"][:3])}{"..." if len(paper["authors"]) > 3 else ""}<br>
        Venue: {paper["venue"]}
        """
        # Size based on c_out
        size = 15 + paper["c_out"] * 5
        net.add_node(
            key,
            label=label,
            title=title_html,
            color=CITING_COLOR,
            shape="triangle",
            size=size,
            borderWidth=2,
        )

    # Add edges
    for src, tgt, etype in graph_data["edges"]:
        net.add_edge(src, tgt)

    # Generate HTML with legend
    net.save_graph(output_path)

    # Add legend to the HTML
    with open(output_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    legend_html = f"""
    <div style="position: fixed; top: 10px; left: 10px; background: white; 
                padding: 15px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                font-family: Arial, sans-serif; z-index: 1000;">
        <h3 style="margin: 0 0 10px 0; font-size: 14px;">Citation Graph Legend</h3>
        <div style="margin: 5px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; 
                        background: {SEED_COLOR}; margin-right: 8px; vertical-align: middle;"></span>
            <span style="font-size: 12px;">Seed Papers (S) - {len(graph_data["seed_papers"])} papers</span>
        </div>
        <div style="margin: 5px 0;">
            <span style="display: inline-block; width: 20px; height: 20px; 
                        background: {CITED_COLOR}; border-radius: 50%; margin-right: 8px; vertical-align: middle;"></span>
            <span style="font-size: 12px;">Cited by ≥{k_cited} seeds (R_k) - {len(graph_data["cited_papers"])} papers</span>
        </div>
        <div style="margin: 5px 0;">
            <span style="display: inline-block; width: 0; height: 0; 
                        border-left: 10px solid transparent; border-right: 10px solid transparent;
                        border-bottom: 18px solid {CITING_COLOR}; margin-right: 8px; vertical-align: middle;"></span>
            <span style="font-size: 12px;">Citing ≥{k_citing} seeds (Q_k') - {len(graph_data["citing_papers"])} papers</span>
        </div>
        <div style="margin-top: 10px; font-size: 11px; color: #666;">
            Edges: paper → cites → paper
        </div>
    </div>
    """

    # Insert legend after <body>
    html_content = html_content.replace("<body>", f"<body>\n{legend_html}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def main():
    parser = argparse.ArgumentParser(
        description="Visualize citation relationships as an interactive graph"
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
        "--output",
        "-o",
        default="graph.html",
        help="Output HTML file (default: graph.html)",
    )

    args = parser.parse_args()

    # Load citation data
    print(f"Loading citation data from: {args.input}")
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    num_seed_papers = len(data.get("papers", []))
    print(f"Seed set contains {num_seed_papers} papers")

    # Analyze and prepare graph data
    print(f"Analyzing with k_cited={args.kcited}, k_citing={args.kciting}...")
    graph_data = analyze_for_graph(data, args.kcited, args.kciting)

    print(f"Graph nodes:")
    print(f"  - Seed papers (S): {len(graph_data['seed_papers'])}")
    print(f"  - Cited papers (R_k): {len(graph_data['cited_papers'])}")
    print(f"  - Citing papers (Q_k'): {len(graph_data['citing_papers'])}")
    print(f"  - Total edges: {len(graph_data['edges'])}")

    # Create visualization
    print(f"Creating visualization...")
    create_visualization(graph_data, args.output, args.kcited, args.kciting)

    print(f"\nVisualization saved to: {args.output}")
    print("Open this file in a web browser to view the interactive graph.")


if __name__ == "__main__":
    main()
