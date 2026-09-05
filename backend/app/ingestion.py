"""EPUB -> heading-aware sections -> explicit character chunks. Never extracts files."""

import hashlib
import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter

PARSER_VERSION = 2


def parse_epub(path: Path) -> list[dict]:
    sections = []
    with ZipFile(path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        package_path = next(e.attrib["full-path"] for e in container.iter() if e.tag.endswith("rootfile"))
        package = ET.fromstring(archive.read(package_path))
        base = posixpath.dirname(package_path)
        title = next((e.text for e in package.iter() if e.tag.endswith("}title")), "AI Engineering")
        if title and title.startswith("AI Engineering"):
            title = "AI Engineering: Building Applications with Foundation Models"
        manifest = {e.attrib["id"]: e.attrib for e in package.iter() if e.tag.endswith("}item")}
        spine = [e.attrib["idref"] for e in package.iter() if e.tag.endswith("}itemref")]
        for item_id in spine:
            item = manifest[item_id]
            if "nav" in item.get("properties", "").split():
                continue
            if "html" not in item.get("media-type", ""):
                continue
            href = posixpath.normpath(posixpath.join(base, unquote(item["href"].split("#")[0])))
            soup = BeautifulSoup(archive.read(href), "html.parser")
            # This textbook has ten chapter files. EPUB chapter semantics are the fallback.
            chapter_element = soup.select_one('section[data-type="chapter"], [epub\\:type="chapter"]')
            if not re.search(r"(?:ch|chapter)\d+\.(?:x?html)$", href, re.I) and not chapter_element:
                continue
            for element in soup.select("nav, script, style, header, footer, .pagebreak"):
                element.decompose()
            heading = soup.find(re.compile(r"^h[1-6]$"))
            chapter = heading.get_text(" ", strip=True) if heading else Path(href).stem
            current = chapter
            anchor = ""
            blocks = []

            def flush():
                text = "\n\n".join(blocks).strip()
                if text:
                    sections.append(
                        {
                            "text": text,
                            "title": title,
                            "chapter": chapter,
                            "section": current,
                            "heading": current,
                            "source_id": href,
                            "anchor": anchor,
                        }
                    )

            for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "table"]):
                if element.find_parent(["li", "pre", "table"]):
                    continue  # Avoid double-counting nested paragraphs and list/table content.
                if re.match(r"h[1-6]", element.name):
                    # O'Reilly uses h6 for figures/admonitions; these are content, not new sections.
                    if element.name == "h6" or element.find_parent(
                        attrs={"data-type": re.compile("note|tip|warning")}
                    ):
                        blocks.append(element.get_text(" ", strip=True))
                        continue
                    flush()
                    blocks = []
                    current = element.get_text(" ", strip=True)
                    anchor = element.get("id", element.parent.get("id", ""))
                else:
                    value = element.get_text("\n" if element.name in ("pre", "table") else " ", strip=True)
                    if value:
                        blocks.append(value)
            flush()
    if not sections:
        raise ValueError("No textbook chapters found. Use the AI Engineering EPUB, not a DRM placeholder.")
    return sections


def chunk_sections(sections: list[dict], size=1400, overlap=200) -> list[dict]:
    # LangChain is plumbing only; boundaries, metadata, and embedding inputs stay visible here.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size, chunk_overlap=overlap, separators=["\n\n", "\n", ". ", " ", ""]
    )
    chunks = []
    for section_index, section in enumerate(sections):
        metadata = {k: v for k, v in section.items() if k != "text"}
        for ordinal, text in enumerate(splitter.split_text(section["text"])):
            identity = f"{metadata['source_id']}:{section_index}:{ordinal}:{text}"
            chunk_id = hashlib.sha256(identity.encode()).hexdigest()[:20]
            chunks.append({"id": chunk_id, "text": text, "metadata": {**metadata, "ordinal": ordinal}})
    return chunks
