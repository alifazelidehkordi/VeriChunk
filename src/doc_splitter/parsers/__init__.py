"""Document parsers producing unified IR."""

from doc_splitter.parsers.docx_parser import parse_docx
from doc_splitter.parsers.pdf_pipeline import parse_pdf

__all__ = ["parse_docx", "parse_pdf"]