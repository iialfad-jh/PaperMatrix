from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen


ARXIV_ID_PATTERN = re.compile(
    r"^(?:arxiv:)?(?P<identifier>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)$",
    re.IGNORECASE,
)
DOI_PATTERN = re.compile(r"^(?:doi:\s*)?(?P<doi>10\.\d{4,9}/[-._;()/:A-Z0-9]+)$", re.IGNORECASE)
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


class SourceError(ValueError):
    pass


def resolve_pdf_paths(source: str, download_dir: str | Path, *, force: bool = False) -> list[Path]:
    local_path = Path(source).expanduser()
    if local_path.exists():
        if not local_path.is_dir():
            raise SourceError(f"Local source must be a folder containing PDFs: {local_path}")
        return sorted(local_path.glob("*.pdf"))

    arxiv_identifier = _parse_arxiv_identifier(source)
    if arxiv_identifier:
        url = f"https://arxiv.org/pdf/{arxiv_identifier}.pdf"
        filename = f"arxiv-{_safe_name(arxiv_identifier)}.pdf"
        destination = _download_pdf(url, Path(download_dir) / filename, force=force)
        _save_source_metadata(
            destination,
            {
                "source_type": "arxiv",
                "input": source,
                "arxiv_id": arxiv_identifier,
                "pdf_url": url,
            },
        )
        return [destination]

    doi = _parse_doi(source)
    if doi:
        return [_resolve_doi_pdf(doi, source, Path(download_dir), force=force)]

    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        filename = _url_filename(source)
        destination = _download_pdf(source, Path(download_dir) / filename, force=force)
        _save_source_metadata(
            destination,
            {"source_type": "direct_url", "input": source, "pdf_url": source},
        )
        return [destination]

    raise SourceError(
        "Source must be a local PDF folder, an arXiv ID/URL, a DOI, or a direct HTTP(S) PDF URL."
    )


def _parse_arxiv_identifier(source: str) -> str | None:
    match = ARXIV_ID_PATTERN.fullmatch(source.strip())
    if match:
        return match.group("identifier")

    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "arxiv.org",
        "www.arxiv.org",
        "export.arxiv.org",
    }:
        return None

    path = unquote(parsed.path).strip("/")
    for prefix in ("abs/", "pdf/"):
        if path.startswith(prefix):
            identifier = path[len(prefix) :]
            if identifier.lower().endswith(".pdf"):
                identifier = identifier[:-4]
            match = ARXIV_ID_PATTERN.fullmatch(identifier)
            return match.group("identifier") if match else None
    return None


def _parse_doi(source: str) -> str | None:
    candidate = source.strip().strip("<>")
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {"doi.org", "dx.doi.org", "www.doi.org"}:
        candidate = unquote(parsed.path).strip("/")
    else:
        candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    candidate = candidate.rstrip(".,;)")
    match = DOI_PATTERN.fullmatch(candidate)
    return match.group("doi") if match else None


def _resolve_doi_pdf(doi: str, input_source: str, download_dir: Path, *, force: bool) -> Path:
    metadata = _fetch_crossref_metadata(doi)
    title = metadata.get("title") or "paper"
    destination = download_dir / _doi_filename(doi, title)
    candidates: list[str] = []

    unpaywall_email = os.environ.get("UNPAYWALL_EMAIL", "").strip()
    if unpaywall_email:
        try:
            unpaywall = _fetch_unpaywall_metadata(doi, unpaywall_email)
            candidates.extend(_unpaywall_pdf_urls(unpaywall))
        except SourceError:
            pass
    candidates.extend(_crossref_pdf_urls(metadata))
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        email_hint = " Set UNPAYWALL_EMAIL to enable OA repository lookup." if not unpaywall_email else ""
        raise SourceError(f"No open PDF link found for DOI {doi}. Crossref title: {title}.{email_hint}")

    errors = []
    for pdf_url in candidates:
        try:
            downloaded_path = _download_pdf(pdf_url, destination, force=force)
            _save_source_metadata(
                downloaded_path,
                {
                    "source_type": "doi",
                    "input": input_source,
                    "doi": doi,
                    "title": title,
                    "authors": metadata.get("authors", []),
                    "published": metadata.get("published"),
                    "container_title": metadata.get("container_title"),
                    "pdf_url": pdf_url,
                },
            )
            return downloaded_path
        except SourceError as exc:
            errors.append(str(exc))

    detail = f" Last error: {errors[-1]}" if errors else ""
    raise SourceError(f"No accessible open PDF found for DOI {doi}.{detail}")


def _fetch_crossref_metadata(doi: str) -> dict:
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    try:
        payload = _fetch_json(url)
        message = payload.get("message", {})
        if not isinstance(message, dict):
            raise ValueError("Crossref response has no message object")
    except (SourceError, ValueError) as exc:
        raise SourceError(f"Could not resolve DOI metadata from Crossref: {doi}") from exc

    title_values = message.get("title") or []
    authors = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        authors.append({key: author[key] for key in ("given", "family") if author.get(key)})
    date_parts = ((message.get("published") or {}).get("date-parts") or [[]])[0]
    return {
        "title": str(title_values[0]) if title_values else "paper",
        "authors": authors,
        "published": date_parts,
        "container_title": (message.get("container-title") or [None])[0],
        "link": message.get("link") or [],
    }


def _fetch_unpaywall_metadata(doi: str, email: str) -> dict:
    query = urlencode({"email": email})
    url = f"https://api.unpaywall.org/v2/{quote(doi, safe='')}?{query}"
    try:
        payload = _fetch_json(url)
    except SourceError as exc:
        raise SourceError(f"Could not resolve OA metadata from Unpaywall: {doi}") from exc
    return payload if isinstance(payload, dict) else {}


def _fetch_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "PaperMatrix/0.1 (+https://github.com/iialfad-jh/PaperMatrix)"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SourceError(f"Could not fetch metadata: {url}") from exc
    if not isinstance(payload, dict):
        raise SourceError(f"Metadata response is not a JSON object: {url}")
    return payload


def _unpaywall_pdf_urls(metadata: dict) -> list[str]:
    locations = []
    best_location = metadata.get("best_oa_location")
    if isinstance(best_location, dict):
        locations.append(best_location)
    locations.extend(location for location in metadata.get("oa_locations", []) if isinstance(location, dict))
    return [str(location["url_for_pdf"]) for location in locations if location.get("url_for_pdf")]


def _crossref_pdf_urls(metadata: dict) -> list[str]:
    urls = []
    for link in metadata.get("link", []):
        if not isinstance(link, dict) or not link.get("URL"):
            continue
        content_type = str(link.get("content-type", "")).lower()
        url = str(link["URL"])
        if content_type == "application/pdf" or urlparse(url).path.lower().endswith(".pdf"):
            urls.append(url)
    return urls


def _doi_filename(doi: str, title: str) -> str:
    title_slug = _safe_name(re.sub(r"\s+", "-", title.lower()))[:80].strip("._-") or "paper"
    digest = hashlib.sha256(doi.lower().encode("utf-8")).hexdigest()[:12]
    return f"doi-{title_slug}-{digest}.pdf"


def _url_filename(url: str) -> str:
    parsed = urlparse(url)
    basename = Path(unquote(parsed.path)).name
    stem = Path(basename).stem if basename.lower().endswith(".pdf") else "paper"
    safe_stem = _safe_name(stem) or "paper"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{safe_stem}-{digest}.pdf"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")


def _save_source_metadata(destination: Path, metadata: dict) -> None:
    metadata_path = destination.with_suffix(".source.json")
    payload = {
        **metadata,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _download_pdf(url: str, destination: Path, *, force: bool) -> Path:
    if destination.exists() and not force:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "PaperMatrix/0.1 (+https://github.com/iialfad-jh/PaperMatrix)"})
    temporary_path: Path | None = None
    try:
        with urlopen(request, timeout=30) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                raise SourceError(f"PDF is larger than the {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB limit: {url}")

            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{destination.stem}-", suffix=".part", dir=destination.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                downloaded = 0
                while block := response.read(64 * 1024):
                    downloaded += len(block)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise SourceError(
                            f"PDF is larger than the {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB limit: {url}"
                        )
                    temporary_file.write(block)

        if temporary_path is None:
            raise SourceError(f"Downloaded content is not a PDF: {url}")
        with temporary_path.open("rb") as downloaded_file:
            pdf_header = downloaded_file.read(1024)
        if b"%PDF-" not in pdf_header:
            raise SourceError(f"Downloaded content is not a PDF: {url}")
        temporary_path.replace(destination)
        return destination
    except SourceError:
        raise
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise SourceError(f"Could not download PDF from {url}: {exc}") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
