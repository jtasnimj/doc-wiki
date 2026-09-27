import sys

import pymupdf

with pymupdf.open() as doc:
    for i in range(4):
        page = doc.new_page()
        page.insert_text(
            (50, 50),
            f"Synthetic diagram page {i + 1}. The figure below contains visual relationships.",
        )
        # Rasterize the figure labels: ordinary PDF extraction cannot see them.
        with pymupdf.open() as image_doc:
            image_page = image_doc.new_page(width=350, height=230)
            image_page.draw_rect((5, 5, 345, 225))
            image_page.insert_text((20, 50), f"Region map {i + 1}", fontsize=20)
            image_page.insert_text((20, 100), "Primary: west -> Backup: east", fontsize=18)
            pix = image_page.get_pixmap()
            page.insert_image((100, 150, 450, 380), stream=pix.tobytes("png"))
    doc.save(sys.argv[1])
