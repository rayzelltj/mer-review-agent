"""
PDF page-text extraction helper.

Tries ``pdfplumber`` first (best layout fidelity), then ``pypdf``, then
``PyPDF2`` for backwards compatibility.  Raises ``ImportError`` only when
*none* of the libraries are available.
"""

from __future__ import annotations

import io


def extract_pages(pdf_bytes: bytes) -> list[str]:
    """Extract text from every page of *pdf_bytes*.

    Returns a ``list[str]`` with one entry per page (empty string if a page
    yielded no extractable text).

    Raises:
        ImportError: if no supported PDF library is installed.
            Install ``pdfplumber`` (recommended) or ``pypdf``.
    """
    errors: list[str] = []

    # --- pdfplumber (best layout/column handling) --------------------------
    try:
        import pdfplumber  # type: ignore[import-untyped]

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except ImportError:
        errors.append("pdfplumber not installed")
    except Exception as exc:  # pragma: no cover
        errors.append(f"pdfplumber error: {exc}")

    # --- pypdf (pure-Python, actively maintained) --------------------------
    try:
        import pypdf  # type: ignore[import-untyped]

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return [page.extract_text() or "" for page in reader.pages]
    except ImportError:
        errors.append("pypdf not installed")
    except Exception as exc:  # pragma: no cover
        errors.append(f"pypdf error: {exc}")

    # --- PyPDF2 (legacy fallback) ------------------------------------------
    try:
        import PyPDF2  # type: ignore[import-untyped]  # noqa: N813

        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        return [page.extract_text() or "" for page in reader.pages]
    except ImportError:
        errors.append("PyPDF2 not installed")
    except Exception as exc:  # pragma: no cover
        errors.append(f"PyPDF2 error: {exc}")

    raise ImportError(
        "No PDF extraction library found. Install pdfplumber or pypdf.\n"
        + "\n".join(f"  • {e}" for e in errors)
    )
