from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


ARXIV_ID_PATTERN = re.compile(
    r"^(?:arxiv:)?(?P<identifier>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)$",
    re.IGNORECASE,
)
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
        return [_download_pdf(url, Path(download_dir) / filename, force=force)]

    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        filename = _url_filename(source)
        return [_download_pdf(source, Path(download_dir) / filename, force=force)]

    raise SourceError(
        "Source must be a local PDF folder, an arXiv ID/URL, or a direct HTTP(S) PDF URL."
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


def _url_filename(url: str) -> str:
    parsed = urlparse(url)
    basename = Path(unquote(parsed.path)).name
    stem = Path(basename).stem if basename.lower().endswith(".pdf") else "paper"
    safe_stem = _safe_name(stem) or "paper"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{safe_stem}-{digest}.pdf"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")


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
