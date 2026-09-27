import sys

import pymupdf

with pymupdf.open() as doc:
    page = doc.new_page()
    page.insert_text((50, 45), "This page contains a continuation row with no header.")
    for x in [50, 180, 320]:
        page.draw_line((x, 80), (x, 130))
    for y in [80, 130]:
        page.draw_line((50, y), (320, y))
    page.insert_text((60, 110), "CC42")
    page.insert_text((190, 110), "Annual review")
    page = doc.new_page()
    page.insert_text((50, 45), "Continuation page with two unnumbered data rows.")
    for x in [50, 180, 320]:
        page.draw_line((x, 80), (x, 170))
    for y in [80, 125, 170]:
        page.draw_line((50, y), (320, y))
    for x, y, text in [
        (60, 110, "Firewall"),
        (190, 110, "Enabled"),
        (60, 155, "Backups"),
        (190, 155, "Daily"),
    ]:
        page.insert_text((x, y), text)
    doc.save(sys.argv[1])
