# Dependency and source redistribution review

Installed package metadata was reviewed for the locked direct runtime dependencies. This is an inventory, not a completed legal clearance or a project-license choice.

| Dependency | Locked version | Declared license |
|---|---|---|
| FastAPI | 0.141.1 | MIT |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| Pydantic | 2.13.5 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| PyMuPDF | 1.26.7 | AGPL-3.0 / Artifex commercial dual licensing |
| llama-index-core | 0.14.25 | MIT |
| llama-index-vector-stores-chroma | 0.5.5 | MIT |
| Chroma | 1.5.9 | Apache-2.0 |
| OpenAI SDK | 2.54.0 | Apache-2.0 |
| tiktoken | 0.14.0 | MIT |
| filelock | 3.32.7 | MIT |

PyMuPDF is the material licensing consideration: its [official licensing statement](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) offers AGPL and commercial agreements. The submitter must decide how the intended distribution/deployment complies; a private assessment is not assumed to waive obligations. No commercial license was bought and no replacement parser was selected. Transitive dependencies remain listed in `uv.lock`; their notices ship with installed distributions. A complete distribution review, including the container base and transitive dependencies, remains a submission responsibility.

The bundled `cl100k_base` vocabulary was downloaded through tiktoken's official loader. Its package license is retained at `src/docwiki/assets/tiktoken/LICENSE`; no runtime tokenizer download is needed. The UI uses system fonts and no downloaded artwork.

The assessment PDF, DOCX, and XLSX are not included in Git or Docker. Public availability of the sample PDF is not treated as permission to redistribute it. Evaluation records cite hashes, questions, evidence locations, and brief factual requirements; full extracted passages stay in ignored local reports. The PDF and JSON under `evaluation/sources/`, examples, and small PDF-generation scripts are authored fixtures. Do not add the original assessment inputs or a populated environment file to a submission repository without reviewing permission.

The repository has no project `LICENSE` file because the user has not selected one. Review the assessment's AI-assistance disclosure rules before publishing or submitting. No remote publication has occurred.
