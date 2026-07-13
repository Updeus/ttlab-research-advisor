# Citation Verification

## Scope and method

This ledger records the 12 July 2026 audit of every entry in
`thesis/references.bib`. Records were checked against the primary publisher,
official proceedings archive, official project record, or standards body shown
below. DOI resolution was tested separately. A citation is marked *verified*
only when its title, complete author list, year, venue or publication type,
pagination where applicable, and DOI or canonical URL agree with that record.
An absent volume, issue, or page range is not an omission when the official
record does not assign one.

The audit does not establish that every sentence in the manuscripts uses the
right citation. The claim column states the support boundary that later prose
editing must respect.

## Verified records and support boundaries

| BibTeX key | Primary or official record | Status | Claim the source can support |
|---|---|---|---|
| `narine2025automating` | [IEEE DOI record](https://doi.org/10.1109/RTSI64020.2025.11212505) and repository copy `narine-rtsi.pdf` | Verified | The precursor scraped and displayed publication metadata, produced lay summaries, sent publication notifications, and used a manual NotebookLM upload/download workflow for podcasts. Its automated query system using RAG is explicitly future work, not an implemented result. |
| `giles1998citeseer` | [ACM DOI record](https://doi.org/10.1145/276675.276685) | Verified | CiteSeer as an automatic citation-indexing and digital-library system. |
| `tang2008arnetminer` | [ACM DOI record](https://doi.org/10.1145/1401890.1402008) | Verified | ArnetMiner's extraction and mining of academic social networks for researcher, topic, and expertise discovery. |
| `ammar2018literaturegraph` | [ACL Anthology record](https://aclanthology.org/N18-3011/) | Verified | Construction of the Semantic Scholar literature graph. It does **not** document the later S2ORC corpus. |
| `lo2020s2orc` | [ACL Anthology record](https://aclanthology.org/2020.acl-main.447/) | Verified; added in this audit | S2ORC's construction and release as the Semantic Scholar Open Research Corpus. |
| `priem2022openalex` | [official arXiv record](https://arxiv.org/abs/2205.01833) | Verified | OpenAlex as a fully open index of scholarly entities and relationships. This is an arXiv preprint, not a journal article. |
| `beel2016researchpaper` | [Springer DOI record](https://doi.org/10.1007/s00799-015-0156-0) | Verified | Surveyed approaches and evaluation challenges in research-paper recommendation. The article appeared online in 2015 and in volume 17(4) in 2016. |
| `sugiyama2010scholarly` | [ACM DOI record](https://doi.org/10.1145/1816123.1816129) | Verified | Scholarly-paper recommendation from a user's recent research interests. |
| `balog2006formal` | [ACM DOI record](https://doi.org/10.1145/1148170.1148181) | Verified | Candidate- and document-based formal models for expert finding. |
| `balog2009language` | [Elsevier DOI record](https://doi.org/10.1016/j.ipm.2008.06.003) | Verified | A language-modeling framework for expert finding. |
| `robertson2009bm25` | [Now Publishers DOI record](https://doi.org/10.1561/1500000019) | Verified | The probabilistic relevance framework and BM25. |
| `weinberger2009featurehashing` | [ACM DOI record](https://doi.org/10.1145/1553374.1553516) | Verified | Feature hashing as a compact signed projection for large-scale learning; it does not make lexical features a learned semantic encoder. |
| `reimers2019sentencebert` | [ACL Anthology record](https://aclanthology.org/D19-1410/) | Verified; official venue title normalized | Sentence-BERT for learned sentence embeddings and semantic similarity. |
| `karpukhin2020dpr` | [ACL Anthology record](https://aclanthology.org/2020.emnlp-main.550/) | Verified; official venue title normalized | Dense Passage Retrieval for open-domain question answering. |
| `cohan2020specter` | [ACL Anthology record](https://aclanthology.org/2020.acl-main.207/) | Verified | Citation-informed document representations for scientific papers. |
| `thakur2021beir` | [official OpenReview record](https://openreview.net/forum?id=wCu6T5xFjeJ) | Verified | BEIR as a heterogeneous zero-shot IR benchmark and evidence that retrieval effectiveness varies by dataset and task. |
| `blei2003lda` | [JMLR record](https://www.jmlr.org/papers/v3/blei03a.html) | Verified | Latent Dirichlet allocation as a probabilistic latent-topic model. |
| `grootendorst2022bertopic` | [official arXiv record](https://arxiv.org/abs/2203.05794) | Verified | BERTopic's embedding, clustering, and class-based TF--IDF topic representation. This is an arXiv preprint. |
| `doogan2021topic` | [ACL Anthology record](https://aclanthology.org/2021.naacl-main.300/) | Verified | Limitations of standard automatic semantic-interpretability measures for topic models. |
| `lewis2020rag` | [NeurIPS proceedings record](https://proceedings.neurips.cc/paper/2020/hash/6b493230-Abstract.html) | Verified | Retrieval-augmented generation that conditions generation on retrieved non-parametric evidence. |
| `izacard2021fid` | [ACL Anthology record](https://aclanthology.org/2021.eacl-main.74/) | Verified | Fusion-in-Decoder aggregation of retrieved passages for open-domain QA. |
| `asai2024selfrag` | [official OpenReview record](https://openreview.net/forum?id=hSyW5go0v8) | Verified | SELF-RAG's learned retrieval and self-reflection control. |
| `es2024ragas` | [ACL Anthology record](https://aclanthology.org/2024.eacl-demo.16/) | Verified | RAGAS's reference-free automated RAG evaluation dimensions. It does not validate this project's outputs by itself. |
| `saadfalcon2024ares` | [ACL Anthology record](https://aclanthology.org/2024.naacl-long.20/) | Verified; official venue title normalized | ARES's synthetic-data and judge-based automated RAG evaluation framework. |
| `min2023factscore` | [ACL Anthology record](https://aclanthology.org/2023.emnlp-main.741/) | Verified | Atomic-fact decomposition and factual-precision evaluation for long-form generation. |
| `fabbri2021summeval` | [MIT Press DOI record](https://doi.org/10.1162/tacl_a_00373) | Verified | SummEval's comparison of automatic and human summarization judgments and its evaluation protocol. |
| `liu2023geval` | [ACL Anthology record](https://aclanthology.org/2023.emnlp-main.153/) | Verified | G-Eval as an LLM-based NLG evaluator with reported correlation to human judgments; it does not make an AI review equivalent to a human study. |
| `amershi2014power` | [AAAI/AI Magazine DOI record](https://doi.org/10.1609/aimag.v35i4.2513) | Verified | Roles for human feedback and interaction in interactive machine learning. |
| `gebru2021datasheets` | [ACM DOI record](https://doi.org/10.1145/3458723) | Verified | Dataset documentation covering motivation, composition, collection, uses, and limitations. |
| `mitchell2019modelcards` | [ACM DOI record](https://doi.org/10.1145/3287560.3287596) | Verified | Model cards for transparent model reporting, intended use, evaluation, and limitations. |
| `weidinger2022taxonomy` | [ACM DOI record](https://doi.org/10.1145/3531146.3533088) | Verified | A taxonomy of language-model risks; it does not quantify the risks of this particular system. |
| `tabassi2023airmf` | [NIST record](https://doi.org/10.6028/NIST.AI.100-1) | Verified | The NIST AI RMF's Govern, Map, Measure, and Manage risk-management functions. |

## Prose follow-up

- `thesis/chapters/01_introduction.tex` and
  `thesis/chapters/04_literature_review.tex` now cite the verified
  `lo2020s2orc` record when naming S2ORC.
- The Narine--Hosein description must retain the manual boundary: publication
  data collection/display, lay summarization, and email notifications were
  implemented; the last five publications were manually uploaded to
  NotebookLM and the audio manually returned to the site; the RAG query system
  appears under future work.

## Validation and residual uncertainty

The bibliography has no duplicate keys or duplicate DOI values. Every
proceedings or journal record contains authors, title, year, venue, and pages;
the official arXiv, OpenReview, JMLR, NeurIPS, and NIST records contain the
fields applicable to their publication type. DOI values are canonical and
resolvable as of the audit date.

No bibliographic entry remains uncertain. Accessibility and security standards were not added in this atomic
pass because no current manuscript citation claims depend on them; if the
rewritten manuscript makes standards-conformance claims, those claims should
cite the exact versioned W3C/NIST/OWASP source rather than a secondary paper.
