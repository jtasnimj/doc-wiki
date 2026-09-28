import sys

import pymupdf

with pymupdf.open() as document:
    page = document.new_page()
    page.insert_text((50, 65), "Equipment records", fontsize=17, fontname="hebo")
    page.insert_text((50, 110), "The register includes portable meters.", fontsize=11)
    page.insert_text((50, 150), "Owners review the register every month.", fontsize=11)
    page.insert_text((50, 190), "READY", fontsize=11, fontname="hebo")
    page.insert_text((50, 235), "Supplier responsibilities", fontsize=17, fontname="hebo")
    page.insert_text((50, 280), "The supplier maintains the cooling system.", fontsize=11)
    for x in (50, 230, 450):
        page.draw_line((x, 320), (x, 400))
    for y in (320, 360, 400):
        page.draw_line((50, y), (450, y))
    cells = [
        (60, 345, "Finding"),
        (240, 345, "Requirement"),
        (60, 385, "Not examined"),
        (240, 385, "Maintain cooling"),
    ]
    for x, y, text in cells:
        if len(sys.argv) > 2 and sys.argv[2] == "reverse":
            x = 240 if x == 60 else 60
        page.insert_text((x, y), text, fontname="hebo" if y == 345 else "helv")
    page = document.new_page()
    page.insert_text((50, 65), "Unrelated page without a heading.", fontsize=11)
    document.save(sys.argv[1])
