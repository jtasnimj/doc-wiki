import sys
from pathlib import Path

import pymupdf

root = Path(sys.argv[1])
with pymupdf.open() as doc:
    doc.new_page()
    doc.save(root / "blank.pdf")
    doc[0].insert_text((50, 50), "Enough readable text to demonstrate the coverage warning.")
    doc.new_page()
    doc.save(root / "partial.pdf")
    doc.save(
        root / "encrypted.pdf",
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="test-owner",
        user_pw="test-reader",
    )
(root / "corrupt.pdf").write_bytes(b"%PDF-1.7 broken body")
