"""Detect and validate the limited set of accepted document formats."""

import re
import struct
import zlib
from pathlib import PurePosixPath
from xml.etree.ElementTree import ParseError
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring
from django.core.exceptions import ValidationError
from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .uploads import MAX_DOCUMENT_BYTES, safe_filename

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
MAX_DOCX_EXPANDED_BYTES = 40 * 1024 * 1024
MAX_DOCX_XML_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
DOCX_MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
CONTENT_TYPES_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
PACKAGE_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
OFFICE_REL_NS = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/",
}
WORD_NS = {
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
    "{http://purl.oclc.org/ooxml/wordprocessingml/main}",
}
TEXT_MARKUP = re.compile(r"\s*(?:<!doctype\s+html\b|<(?:html|head|body|script|svg)\b)", re.I)


def validate_docx(file):
    with ZipFile(file) as package:
        members = package.infolist()
        names = [member.filename.casefold() for member in members]
        if (
            len(members) > 2048
            or len(names) != len(set(names))
            or sum(member.file_size for member in members) > MAX_DOCX_EXPANDED_BYTES
            or any(
                member.flag_bits & 1
                or member.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                or not valid_package_path(member.filename)
                or PurePosixPath(member.filename).name.casefold().startswith("vbaproject.")
                for member in members
            )
        ):
            raise ValueError

        def read_xml(name):
            if package.getinfo(name).file_size > MAX_DOCX_XML_BYTES:
                raise ValueError
            return fromstring(package.read(name), forbid_dtd=True)

        types = read_xml("[Content_Types].xml")
        relationships = read_xml("_rels/.rels")
        document = read_xml("word/document.xml")
        if (
            types.tag != CONTENT_TYPES_NS + "Types"
            or not any(
                item.tag == CONTENT_TYPES_NS + "Override"
                and item.get("PartName") == "/word/document.xml"
                and item.get("ContentType") == DOCX_MAIN_TYPE
                for item in types
            )
            or any("macroenabled" in item.get("ContentType", "").lower() for item in types)
            or relationships.tag != PACKAGE_REL_NS + "Relationships"
            or not any(
                item.tag == PACKAGE_REL_NS + "Relationship"
                and item.get("Type") in {ns + "officeDocument" for ns in OFFICE_REL_NS}
                and item.get("Target") in {"word/document.xml", "/word/document.xml"}
                and item.get("TargetMode", "Internal") == "Internal"
                for item in relationships
            )
            or not any(
                document.tag == ns + "document" and document.find(ns + "body") is not None
                for ns in WORD_NS
            )
            or package.testzip() is not None
        ):
            raise ValueError


def valid_package_path(name):
    path = PurePosixPath(name)
    return (
        not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name
    )


def detect_media_type(file):
    prefix = file.read(16)
    file.seek(0)
    if prefix.startswith(b"%PDF-"):
        file.seek(-min(file.size, 4096), 2)
        tail = file.read().rstrip()
        if not tail.endswith((b"\n%%EOF", b"\r%%EOF")):
            raise ValueError
        file.seek(0)
        pdf = PdfReader(file, strict=True)
        if pdf.is_encrypted or len(pdf.pages) < 1:
            raise ValueError
        return MEDIA_TYPES[".pdf"]
    if prefix.startswith(b"PK\x03\x04"):
        validate_docx(file)
        return MEDIA_TYPES[".docx"]
    if prefix.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
        expected = "PNG" if prefix.startswith(b"\x89PNG") else "JPEG"
        trailer = b"\x00\x00\x00\x00IEND\xaeB`\x82" if expected == "PNG" else b"\xff\xd9"
        if file.size < len(trailer):
            raise ValueError
        file.seek(-len(trailer), 2)
        if file.read() != trailer:
            raise ValueError
        file.seek(0)
        with Image.open(file, formats=[expected]) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError
            if getattr(image, "is_animated", False):
                raise ValueError
            image.verify()
        file.seek(0)
        with Image.open(file, formats=[expected]) as image:
            image.load()
        return "image/png" if expected == "PNG" else "image/jpeg"

    text = file.read(MAX_DOCUMENT_BYTES + 1).decode("utf-8-sig")
    if (
        not text.strip()
        or TEXT_MARKUP.match(text)
        or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text)
    ):
        raise ValueError
    return MEDIA_TYPES[".txt"]


def validate_upload(file):
    if not safe_filename(file.name):
        raise ValidationError("Use a filename without path components or control characters.")
    if not 0 < file.size <= MAX_DOCUMENT_BYTES:
        raise ValidationError("Upload a nonempty file no larger than 10 MiB.")
    expected = MEDIA_TYPES.get(PurePosixPath(file.name).suffix.lower())
    if expected is None:
        raise ValidationError("Upload a PDF, DOCX, UTF-8 TXT, JPG, or PNG file.")
    try:
        detected = detect_media_type(file)
    except (
        BadZipFile,
        DefusedXmlException,
        Image.DecompressionBombError,
        KeyError,
        NotImplementedError,
        OSError,
        OverflowError,
        ParseError,
        PyPdfError,
        RecursionError,
        RuntimeError,
        SyntaxError,
        TypeError,
        ValueError,
        struct.error,
        zlib.error,
    ) as exc:
        raise ValidationError(
            "The file is corrupt, encrypted, or uses an unsupported format."
        ) from exc
    finally:
        file.seek(0)
    if detected != expected:
        raise ValidationError("The file contents do not match its filename extension.")
    return detected
