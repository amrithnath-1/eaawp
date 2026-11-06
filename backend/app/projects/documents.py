"""Project document intelligence (ported from Vyuham): validation, text extraction, chunking, indexing and retrieval.

Validation, extraction (PDF, DOCX, PPTX, XLSX, CSV, TXT) and chunking are Vyuham's. Storage is EAAWP's database
(pm_documents / pm_chunks, tenant-scoped). Retrieval is lexical BM25 scoring in Python over one project's current chunks
(portable across SQLite and PostgreSQL), as Vyuham's FTS5 retrieval was. All extracted text is untrusted: suspicious
passages are flagged and always passed to the model as data.
"""
import csv
import hashlib
import io
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException

ALLOWED = {".pdf", ".docx", ".pptx", ".txt", ".csv", ".xlsx"}
RESUME_ALLOWED = {".pdf", ".docx", ".txt"}
MAX_BYTES = 20 * 1024 * 1024
MAX_UNZIPPED = 200 * 1024 * 1024
CHUNK_CHARS = 1000
CHUNK_OVERLAP = 150

INJECTION_RE = re.compile(
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|prompts?)|disregard (the )?(system|previous)|"
    r"you are now|system prompt|reveal (your|the) (instructions|prompt|api key)|act as (an? )?(admin|administrator)|"
    r"assign all tasks to", re.I)
STOPWORDS = set("a an and are as at be but by can do does for from has have how i in is it its me my of on or our should "
                "that the their this to was we what when where which who why will with would you your about please tell".split())


def validate_upload(filename: str, data: bytes, allowed=ALLOWED) -> str:
    name = Path(filename or "").name
    ext = Path(name).suffix.lower()
    if not name or ext not in allowed:
        raise ValueError(f"Unsupported file type '{ext or 'none'}'. Allowed: {', '.join(sorted(allowed))}")
    if not data:
        raise ValueError("The file is empty")
    if len(data) > MAX_BYTES:
        raise ValueError(f"File is {len(data) // (1024 * 1024)} MB; the limit is {MAX_BYTES // (1024 * 1024)} MB")
    if ext == ".pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        raise ValueError("This file does not look like a real PDF")
    if ext in (".docx", ".pptx", ".xlsx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                    raise ValueError("The archive expands to an unsafe size")
        except zipfile.BadZipFile:
            raise ValueError(f"This file is not a valid {ext} document")
    return ext


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def extract(ext: str, data: bytes) -> List[Tuple[str, str]]:
    """Returns (location, text) sections; location is a page, slide, sheet or section reference."""
    if ext == ".txt":
        return [("Text", _decode(data))]
    if ext == ".csv":
        rows = list(csv.reader(io.StringIO(_decode(data))))
        return [("CSV rows", "\n".join(" | ".join(r) for r in rows[:5000]))]
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return [(f"Page {i + 1}", p.extract_text() or "") for i, p in enumerate(reader.pages)]
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        out: List[Tuple[str, str]] = []
        section, buf = "Document", []
        for para in d.paragraphs:
            if para.style is not None and para.style.name.startswith("Heading") and para.text.strip():
                if buf:
                    out.append((section, "\n".join(buf)))
                section, buf = f"Section: {para.text.strip()[:80]}", []
            elif para.text.strip():
                buf.append(para.text.strip())
        if buf:
            out.append((section, "\n".join(buf)))
        for i, table in enumerate(d.tables):
            out.append((f"Table {i + 1}", "\n".join(" | ".join(c.text.strip() for c in r.cells) for r in table.rows)))
        return out
    if ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        out = []
        for i, slide in enumerate(prs.slides):
            texts = [s.text_frame.text.strip() for s in slide.shapes if s.has_text_frame and s.text_frame.text.strip()]
            for s in slide.shapes:
                if s.has_table:
                    texts.extend(" | ".join(c.text.strip() for c in r.cells) for r in s.table.rows)
            out.append((f"Slide {i + 1}", "\n".join(texts)))
        return out
    if ext == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            lines = []
            for row in ws.iter_rows(values_only=True, max_row=5000):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    lines.append(" | ".join(cells))
            out.append((f"Sheet: {ws.title}", "\n".join(lines)))
        return out
    raise ValueError(f"No extractor for {ext}")


def chunk_sections(sections: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    chunks: List[Tuple[str, str]] = []
    for location, text in sections:
        text = re.sub(r"[ \t]+", " ", text).strip()
        start = 0
        while start < len(text):
            end = min(len(text), start + CHUNK_CHARS)
            if end < len(text):   # prefer a sentence or line boundary
                cut = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
                if cut > start + CHUNK_CHARS // 2:
                    end = cut + 1
            piece = text[start:end].strip()
            if piece:
                chunks.append((location, piece))
            if end >= len(text):
                break
            start = end - CHUNK_OVERLAP
    return chunks


# ------------------------------------------------------------------ storage (EAAWP database)
import math  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db.pm_models import PmChunk, PmDocument  # noqa: E402


def _doc_dict(d: PmDocument) -> Dict:
    return {"id": d.id, "project_id": d.project_id, "filename": d.filename, "version": d.version, "size": d.size, "ext": d.ext,
            "status": d.status, "error": d.error, "is_current": d.is_current, "chunk_count": d.chunk_count,
            "suspicious_count": d.suspicious_count, "uploaded_by": d.uploaded_by,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None}


async def store_and_index(db: AsyncSession, tenant_id: str, project_id: str, filename: str, data: bytes, actor: str) -> Dict:
    """Validate, extract, chunk and index one upload (a new version supersedes older ones). Failures are recorded on the
    document, never raised, except for files that are refused outright (type, size, signature)."""
    ext = validate_upload(filename, data)
    name = Path(filename).name[:255]
    sha = hashlib.sha256(data).hexdigest()
    dup = (await db.execute(select(PmDocument).where(PmDocument.tenant_id == tenant_id, PmDocument.project_id == project_id,
                                                     PmDocument.sha256 == sha, PmDocument.is_current == True))).scalar_one_or_none()  # noqa: E712
    if dup:
        return {**_doc_dict(dup), "duplicate": True}
    prev = (await db.execute(select(PmDocument).where(PmDocument.tenant_id == tenant_id, PmDocument.project_id == project_id,
                                                      PmDocument.filename == name))).scalars().all()
    doc = PmDocument(tenant_id=tenant_id, project_id=project_id, filename=name, version=max([p.version for p in prev], default=0) + 1,
                     sha256=sha, size=len(data), ext=ext, status="extracting", uploaded_by=actor[:255])
    db.add(doc)
    await db.flush()
    try:
        chunks = chunk_sections(extract(ext, data))
        if not chunks:
            raise ValueError("No readable text found. A scanned PDF needs OCR before it can be indexed.")
        suspicious = 0
        for seq, (location, text) in enumerate(chunks):
            flag = bool(INJECTION_RE.search(text))
            suspicious += int(flag)
            db.add(PmChunk(tenant_id=tenant_id, document_id=doc.id, project_id=project_id, seq=seq, location=location[:160],
                           text=text, suspicious=flag))
        for old in prev:
            if old.is_current:
                await db.execute(delete(PmChunk).where(PmChunk.tenant_id == tenant_id, PmChunk.document_id == old.id))
                old.is_current, old.status, old.chunk_count = False, "superseded", 0
        doc.status, doc.chunk_count, doc.suspicious_count, doc.error = "indexed", len(chunks), suspicious, None
    except Exception as exc:   # corrupt or unreadable files surface as a status, not a crash
        doc.status, doc.error = "failed", str(exc)[:400]
    await db.flush()
    return _doc_dict(doc)


async def list_documents(db: AsyncSession, tenant_id: str, project_id: str) -> List[Dict]:
    rows = (await db.execute(select(PmDocument).where(PmDocument.tenant_id == tenant_id, PmDocument.project_id == project_id)
                             .order_by(PmDocument.is_current.desc(), PmDocument.uploaded_at.desc()))).scalars().all()
    return [_doc_dict(d) for d in rows]


async def get_document(db: AsyncSession, tenant_id: str, project_id: str, document_id: str) -> PmDocument:
    doc = (await db.execute(select(PmDocument).where(PmDocument.tenant_id == tenant_id, PmDocument.project_id == project_id,
                                                     PmDocument.id == document_id))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Document not found in this project")
    return doc


async def delete_document(db: AsyncSession, tenant_id: str, project_id: str, document_id: str) -> None:
    doc = await get_document(db, tenant_id, project_id, document_id)
    await db.execute(delete(PmChunk).where(PmChunk.tenant_id == tenant_id, PmChunk.document_id == doc.id))
    await db.delete(doc)
    await db.flush()


async def preview(db: AsyncSession, tenant_id: str, project_id: str, document_id: str, limit: int = 6) -> Dict:
    doc = await get_document(db, tenant_id, project_id, document_id)
    rows = (await db.execute(select(PmChunk).where(PmChunk.tenant_id == tenant_id, PmChunk.document_id == doc.id)
                             .order_by(PmChunk.seq).limit(limit))).scalars().all()
    return {"filename": doc.filename, "version": doc.version, "status": doc.status,
            "chunks": [{"location": c.location, "text": c.text, "suspicious": c.suspicious} for c in rows]}


async def _current_chunks(db: AsyncSession, tenant_id: str, project_id: str) -> List[Dict]:
    q = (select(PmChunk, PmDocument).join(PmDocument, PmDocument.id == PmChunk.document_id)
         .where(PmChunk.tenant_id == tenant_id, PmChunk.project_id == project_id, PmDocument.tenant_id == tenant_id,
                PmDocument.is_current == True, PmDocument.status == "indexed")  # noqa: E712
         .order_by(PmDocument.uploaded_at, PmChunk.seq))
    return [{"id": c.id, "text": c.text, "location": c.location, "suspicious": c.suspicious, "filename": d.filename,
             "version": d.version} for c, d in (await db.execute(q)).all()]


def _words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]{2,}", text.lower()) if w not in STOPWORDS]


async def search(db: AsyncSession, tenant_id: str, project_id: str, query: str, limit: int = 6) -> List[Dict]:
    """BM25 over one project's current chunks (never another project's)."""
    terms = list(dict.fromkeys(_words(query)))[:20]
    if not terms:
        return []
    chunks = await _current_chunks(db, tenant_id, project_id)
    if not chunks:
        return []
    docs = [_words(c["text"]) for c in chunks]
    avg = sum(len(d) for d in docs) / len(docs)
    df = {t: sum(1 for d in docs if t in d) for t in terms}
    scored = []
    for c, words in zip(chunks, docs):
        score = 0.0
        for t in terms:
            f = words.count(t)
            if not f:
                continue
            idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(words) / max(avg, 1)))
        if score > 0:
            scored.append({**c, "rank": round(score, 4)})
    scored.sort(key=lambda x: (-x["rank"], x["id"]))
    return scored[:limit]


async def project_text(db: AsyncSession, tenant_id: str, project_id: str, max_chars: int = 150_000) -> Tuple[List[Dict], bool]:
    """All current chunks for a project, up to the context limit. The flag reports truncation."""
    out, total = [], 0
    for r in await _current_chunks(db, tenant_id, project_id):
        total += len(r["text"])
        if total > max_chars:
            return out, True
        out.append(r)
    return out, False


def as_untrusted_block(chunks: List[Dict]) -> str:
    parts = []
    for c in chunks:
        warn = ' flagged="possible-prompt-injection"' if c.get("suspicious") else ""
        parts.append(f'<untrusted_document source="{c["filename"]}" location="{c["location"]}"{warn}>\n{c["text"]}\n</untrusted_document>')
    return "\n".join(parts)
