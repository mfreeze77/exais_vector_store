from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

BASE_URL = "https://topeka.municipal.codes"
ROOT_PATH = "/TMC"

_SPACE_RE = re.compile(r"[\t\r\f\v ]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def normalize_space(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\xa0", " ")
    value = _SPACE_RE.sub(" ", value)
    return value.strip()


def normalize_text(value: str) -> str:
    lines = [normalize_space(line) for line in value.splitlines()]
    value = "\n".join(line for line in lines if line)
    return _MULTI_NL_RE.sub("\n\n", value).strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonicalize_url(url: str, base_url: str = BASE_URL) -> str | None:
    absolute = urljoin(base_url, url)
    parts = urlsplit(absolute)
    if parts.scheme not in {"http", "https"}:
        return None
    if parts.netloc.lower() != urlsplit(base_url).netloc.lower():
        return None
    path = parts.path.rstrip("/") or "/"
    if path != ROOT_PATH and not path.startswith(ROOT_PATH + "/"):
        return None
    return urlunsplit(("https", parts.netloc.lower(), path, "", ""))


def source_path(url: str) -> str:
    return urlsplit(url).path.rstrip("/") or "/"


def stable_page_id(url: str, jurisdiction_id: str = "ks-topeka") -> str:
    path = source_path(url)
    suffix = path.removeprefix("/TMC").strip("/") or "root"
    suffix = suffix.replace("/", ":")
    return f"{jurisdiction_id}:tmc:{suffix}"


def stable_child_id(parent_id: str, kind: str, value: str) -> str:
    slug = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:80] or sha256_text(value)[:12]
    return f"{parent_id}:{kind}:{slug}"
