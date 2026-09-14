"""Create immutable source packets outside Brain; no model calls or vault writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

VAULT = Path(os.environ.get("BRAIN_VAULT_ROOT") or Path.home() / "Documents/Brain").expanduser().resolve()

def extract(source):
    ext = source.suffix.lower()
    sections, warnings = [], []
    if ext == ".pdf":
        import pymupdf as fitz
        with fitz.open(source) as doc:
            if doc.needs_pass:
                raise ValueError("Encrypted PDF requires an unlocked source copy")
            for n, page in enumerate(doc, 1):
                text = page.get_text().strip()
                if not text:
                    warnings.append(f"Page {n}: no extracted text; visual review/OCR required")
                if page.get_images():
                    warnings.append(f"Page {n}: images present; inspect original for meaningful content")
                sections.append((f"Page {n}", text or "[No extracted text]"))
        warnings.append("PDF layout, drawings, tables and equations require original-page review")
    elif ext == ".docx":
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with zipfile.ZipFile(source) as z:
            root = ET.fromstring(z.read("word/document.xml"))
        body = root.find("w:body", ns)
        for n, el in enumerate(body, 1):
            kind = el.tag.rsplit("}", 1)[-1]
            if kind == "p":
                text = "".join(t.text or "" for t in el.findall(".//w:t", ns))
                if text:
                    sections.append((f"Paragraph {n}", text))
            elif kind == "tbl":
                rows = [" | ".join("".join(t.text or "" for t in cell.findall(".//w:t", ns)) for cell in row.findall("w:tc", ns)) for row in el.findall("w:tr", ns)]
                sections.append((f"Table {n}", "\n".join(rows)))
        warnings.append("DOCX main-body text only; inspect original for images, headers, footnotes, comments and formatting")
    elif ext in {".txt", ".md"}:
        sections = [("Document", source.read_text(encoding="utf-8-sig"))]
    else:
        raise ValueError("Supported sources: PDF, DOCX, UTF-8 TXT or Markdown")
    return sections, warnings

def packet(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == VAULT or VAULT in output.parents:
        raise ValueError("Write packets to the project folder, not Brain; use vaultctl for notes")
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    target = output / digest
    if target.exists():
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        for name, expected in manifest["files"].items():
            if hashlib.sha256((target / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"Existing packet changed: {name}")
        return target
    sections, warnings = extract(source)
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError("Source changed during extraction; retry with a stable copy")
    output.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".packet-", dir=output))
    try:
        original_name = "original" + source.suffix.lower()
        (staging / original_name).write_bytes(data)
        md = f"# {source.name}\n\nSource SHA-256: `{digest}`\n\n"
        md += "## Extraction limitations\n\n" + ("\n".join("- " + w for w in warnings) or "- Plain text extraction; source claims remain unverified.") + "\n\n"
        md += "\n\n".join(f"## {heading}\n\n{text}" for heading, text in sections) + "\n"
        (staging / "extracted.md").write_text(md, encoding="utf-8")
        manifest = {"format": 1, "source_name": source.name, "source_sha256": digest,
                    "anchors": [h for h, _ in sections], "warnings": warnings,
                    "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in staging.iterdir()}}
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        staging.rename(target)
    finally:
        if staging.exists() and staging.resolve().parent == output:
            shutil.rmtree(staging)
    return target

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(packet(args.source, args.output))
