"""Compile Deliverables 3, 4 & Executive Beamer Deck (.tex) via pdflatex and verify page/emoji constraints."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pymupdf

BASE_DIR = Path(__file__).resolve().parent.parent
DELIV_DIR = BASE_DIR / "deliverables"

# Tuple of (tex_path, exact_expected_pages)
TEX_TARGETS = (
    (DELIV_DIR / "03_One_Page_Guide_Real_Time_Sales_Tracker.tex", 1),
    (DELIV_DIR / "04_AI_Usage_and_Validation_Note.tex", 1),
    (DELIV_DIR / "05_Executive_Presentation_Real_Time_Sales_Tracker.tex", 8),
)

EMOJI_PATTERN = re.compile(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200D]")
CLEANUP_EXTENSIONS = (".aux", ".log", ".out", ".nav", ".snm", ".toc", ".vrb")


def compile_tex(tex_path: Path) -> Path:
    """Compile a .tex file twice with pdflatex, clean auxiliary files, and return the PDF path."""
    if not tex_path.exists():
        raise FileNotFoundError(f"LaTeX source not found: {tex_path}")

    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={tex_path.parent}",
        str(tex_path),
    ]
    for pass_num in (1, 2):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="latin-1",
            errors="replace",
            cwd=str(tex_path.parent),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pdflatex failed on {tex_path.name} (pass {pass_num}):\n{result.stdout[-1500:]}\n{result.stderr}"
            )

    for ext in CLEANUP_EXTENSIONS:
        aux_file = tex_path.with_suffix(ext)
        if aux_file.exists():
            aux_file.unlink()

    return tex_path.with_suffix(".pdf")


def verify_pdf(pdf_path: Path, expected_pages: int) -> int:
    """Assert the compiled PDF matches exact expected page count and contains zero emojis."""
    with pymupdf.open(str(pdf_path)) as doc:
        pages = len(doc)
        if pages != expected_pages:
            raise AssertionError(
                f"Expected strictly {expected_pages} page(s) for {pdf_path.name}, got {pages} pages."
            )
        extracted = "".join(page.get_text() for page in doc)
        hits = EMOJI_PATTERN.findall(extracted)
        if hits:
            raise AssertionError(f"Forbidden emoji/pictograph found in {pdf_path.name}: {hits}")
    return pages


def main() -> None:
    for tex_path, expected_pages in TEX_TARGETS:
        pdf_path = compile_tex(tex_path)
        pages = verify_pdf(pdf_path, expected_pages)
        print(f"[OK] {pdf_path.name}: {pages} page(s) verified, 0 emojis ({pdf_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
