"""Dependency-free PDF and DOCX exam paper exports."""

from html import escape
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


def _lines(title: str, sections: dict[str, list[dict]], marks: int) -> list[str]:
    output = [
        title,
        "",
        f"Total marks: {sum(len(rows) * marks for rows in sections.values())}",
        "",
    ]
    for section, questions in sections.items():
        output.extend([section, ""])
        for index, item in enumerate(questions, 1):
            output.append(f"{index}. {item['question']} [{marks} marks]")
            for choice, option in enumerate(item.get("options") or [], 1):
                output.append(f"   {chr(64 + choice)}. {option}")
            output.append("")
    output.extend(["Marking scheme", ""])
    for section, questions in sections.items():
        for index, item in enumerate(questions, 1):
            output.append(
                f"{section} {index}: {item['correct_answer']} — "
                f"{item.get('explanation', '')}"
            )
    return output


def export_pdf(
    title: str, sections: dict[str, list[dict]], marks_per_question: int = 1
) -> bytes:
    """Create a small valid single-page PDF without external system packages."""
    text = "BT /F1 10 Tf 50 790 Td 12 TL "
    for line in _lines(title, sections, marks_per_question):
        safe = (
            line.encode("ascii", "replace")
            .decode()
            .replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )
        text += f"({safe[:115]}) Tj T* "
    text += "ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = text.encode("ascii", "replace")
    objects.append(
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream"
    )
    output = BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = output.tell()
    output.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{start}\n%%EOF".encode()
    )
    return output.getvalue()


def export_docx(
    title: str, sections: dict[str, list[dict]], marks_per_question: int = 1
) -> bytes:
    """Create an Office Open XML document with questions and marking scheme."""
    paragraphs = _lines(title, sections, marks_per_question)
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'
        for line in paragraphs
    )
    document = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body>"
        + body
        + "<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
        "<Default Extension='rels' ContentType='application/vnd.openxmlformats-"
        "package.relationships+xml'/><Default Extension='xml' "
        "ContentType='application/xml'/>"
        "<Override PartName='/word/document.xml' "
        "ContentType='application/vnd.openxmlformats-"
        "officedocument.wordprocessingml.document.main+xml'/></Types>"
    )
    rels = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/"
        "2006/relationships/officeDocument' "
        "Target='word/document.xml'/></Relationships>"
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return output.getvalue()
