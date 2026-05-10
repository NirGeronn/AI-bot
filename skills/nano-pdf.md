---
name: nano-pdf
description: Read text from PDF files (local paths or URLs) for analysis or summarization
---

## PDF

Use the **read_pdf** tool when the user shares a PDF (local path on the VM or a URL) and wants you to read, summarize, or answer questions about it.

When to use:
- User says "read this pdf", "summarize this paper", "what does this document say".
- Input is a `.pdf` URL, a Gmail attachment path, or any local path ending in `.pdf`.

Behavior:
- The tool returns extracted text. If the PDF is scanned (no extractable text), the tool will report that and you should tell the user it needs OCR (not currently supported).
- Long PDFs are truncated; ask the user if they want a specific section.
- After reading, follow user intent: summarize, extract specific data, or answer questions grounded in the text.
