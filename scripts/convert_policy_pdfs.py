from __future__ import annotations

import re
from pathlib import Path

from markitdown import MarkItDown


ROOT = Path(__file__).resolve().parents[1]
POLICY_DIRECTORIES = (
    ROOT / "knowledge" / "insurance-comparisons-au",
    ROOT / "knowledge" / "banking-comparisons-au",
)
PAGE_NUMBER = re.compile(r"\s*(\d{1,3})\s*")


def add_page_markers(markdown: str) -> str:
    lines: list[str] = []
    for line in markdown.splitlines():
        match = PAGE_NUMBER.fullmatch(line)
        if match:
            lines.append(f"<!-- Page: {int(match.group(1))} -->")
        else:
            lines.append(line)
    return "\n".join(lines).strip() + "\n"


def convert_policy_pdfs() -> list[Path]:
    converter = MarkItDown()
    converted: list[Path] = []
    for directory in POLICY_DIRECTORIES:
        for pdf_path in sorted(directory.glob("*.pdf")):
            result = converter.convert(str(pdf_path))
            markdown = result.text_content.strip()
            if not markdown:
                raise ValueError(f"MarkItDown returned no text for {pdf_path}")
            output_path = pdf_path.with_suffix(".md")
            output_path.write_text(add_page_markers(markdown), encoding="utf-8")
            converted.append(output_path)
            print(f"Converted {pdf_path.relative_to(ROOT)} -> {output_path.relative_to(ROOT)}")
    if not converted:
        raise FileNotFoundError("No policy PDFs found under the configured knowledge directories.")
    return converted


def main() -> None:
    convert_policy_pdfs()


if __name__ == "__main__":
    main()
