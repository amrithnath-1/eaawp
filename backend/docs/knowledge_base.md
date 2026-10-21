# Knowledge base (Phase K part 2)

Pipeline: admin upload -> extract (pdf/docx/txt/csv/xlsx) -> chunk -> Gemini embeddings -> `document_chunks` -> cosine retrieval.

## Access control (enforced in retrieval, listing and detail)
| Document access level | Who may read/search it directly | Used by AI employees answering for... |
|---|---|---|
| All staff | everyone in the tenant | everyone |
| Managers | managers + admins | managers + admins |
| Admins | admins | admins |
| AI only | nobody directly (admins can still list it) | any asker (the AI may use it; people cannot browse it) |

- Retrieval always joins `knowledge_documents`: same tenant, `status == indexed`, access level in the asker's set. No asker information -> "All staff" only.
- `POST /knowledge/retrieve`: non-admins cannot pick a `role_scope` (it is ignored); needs only the Gemini key (was wrongly gated on an OpenAI key).
- `GET /knowledge/documents[/{id}]`: documents above the member's level are hidden (404, same as missing).
- Upload (admin only): `role_scope` and `access_level` validated; extracted text capped at 2,000,000 chars (clear "too large" failure).
- Agent tool `fetch_knowledge_base` and execution RAG pre-work pass the asker's role; marketing content generation uses All staff + AI only.
- Source names in tool results were blank; now filled from the document.

## Verification
`tests/test_knowledge_access.py` (19): real upload/extract (txt, docx, blank pdf fails cleanly)/chunk/retrieve with a deterministic fake embedder. NOT verified: live Gemini embeddings, quality of retrieval at scale (SQLite/numpy cosine; pgvector is future work).
