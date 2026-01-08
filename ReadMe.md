## Problem description: citation-based analysis of a fixed paper set

Given a **finite set of scientific papers** ( $S = \{p_1, \dots, p_n\}$ ), identified for example by DOI or another unique identifier, I want to perform a **restricted citation analysis** relative to this set.

The goal is to compute **two derived paper lists**, based on citation counts **with respect to the set (S) only**.

---

### 1. Frequently cited references (incoming from the set)

For every paper $r$ (not necessarily in $S$), define
$$ c_{\text{in}}(r) = \#\{ p \in S \mid p \text{ cites } r \} $$

I want to extract the list
$$ R_k = \{ r \mid c_{\text{in}}(r) \ge k \} $$
i.e. **all papers that are cited by at least ($k_{cited}$) distinct papers in the set ($S$)**.

Each paper ($r \in R_{k_{cited}}$) should be returned together with:

* its identifier (DOI or equivalent),
* its bibliographic metadata (title, authors, year, venue),
* the value ($c_{\text{in}}(r)$).

---

### 2. Papers that cite many papers from the set (outgoing toward the set)

For every paper $q$ (not necessarily in $S$), define
$$ c_{\text{out}}(q) = \#\{ p \in S \mid q \text{ cites } p \} $$

I want to extract the list
$$ Q_{k'} = \{ q \mid c_{\text{out}}(q) \ge k' \} $$
i.e. **all papers that cite at least ($k_{citing}$) distinct papers from the set ($S$)**.

Each paper ($q \in Q_{k_{citing}}$) should be returned together with:

* its identifier,
* its bibliographic metadata,
* the value ($c_{\text{out}}(q)$).
---

### 3. Scope and constraints

* The citation counts ($c_{\text{in}}$) and ($c_{\text{out}}$) must be computed **only relative to the fixed set ($S$)**, not global citation counts.
* Papers in ($R_{k_{cited}}$) or ($Q_{k_{citing}}$) may or may not belong to ($S$).
* The thresholds ($k_{cited}$) and ($k_{citing}$) are user-defined parameters.
* The result should be reproducible and scriptable (e.g. via a public citation graph such as OpenAlex or Semantic Scholar).

---

### 4. Expected output

The final output consists of:

1. A structured list (CSV / JSON / BibTeX) of papers cited by at least (k) papers in (S).
2. A structured list (CSV / JSON / BibTeX) of papers citing at least (k') papers in (S).

Optionally, the implementation may also report:

* citation overlaps inside (S),
* summary statistics (distributions of (c_{\text{in}}), (c_{\text{out}})),
* or a graph representation of the induced citation network.

---

If you want, I can also:

* shorten this to a **one-paragraph spec**,
* rewrite it in a **more informal / product-oriented** style,
* or adapt it to a **grant / internal project / email request** tone.


## First steps

### Implement a function to fetch paper metadata and citations from a public API (e.g., OpenAlex).

The goal is to have a function that takes a DOI as input and returns the list of papers it cites and the list of papers that cite it. Then we could have a first script which takes as input a file with a list of DOIs (one per line) and outputs for each DOI the list of papers it cites and the list of papers that cite it (in JSON format for example).

```python
python get_citations.py --input doi_list.txt --output output/citations.json
```

### Getting the k_in and k_out lists

Using the output of the previous step, we can then implement a second script which takes as input the JSON file with the citations and computes the two lists $R_{k_{cited}}$ and $Q_{k_{citing}}$. In the `k_cited` file should contains the name of the cited paper, its metadata and the list of papers in the seed set that cite it. In the `k_citing` file should contains the name of the citing paper, its metadata and the list of papers in the seed set that it cites.

```python
python analyze_citations.py --input output/citations.json --kcited 2 --kciting 2 --output-cited output/k_cited.json --output-citing output/k_citing.json
```

### Graph visualization

Now we aim to create a visualization of the citation relationships among the papers in the seed set and the papers in the two lists $R_{k_{cited}}$ and $Q_{k_{citing}}$. Paper in the seed, paper cited and paper citing should be represented as nodes of different colors or/and shapes.

```python
python visualize_citations.py --input output/citations.json --kcited 2 --kciting 2 --output output/graph.html
```
