"""Generate our own tiny, redistributable fixture in an isolated process."""

import sys

import pymupdf

doc = pymupdf.open()
page = doc.new_page()
page.insert_text((50, 45), "Example policy. Incident contacts are notified without undue delay.")
for x in (50, 180, 320):
    page.draw_line((x, 80), (x, 160))
for y in (80, 120, 160):
    page.draw_line((50, y), (320, y))
for x, y, text in [
    (60, 105, "Control"),
    (190, 105, "Result"),
    (60, 145, "CC1"),
    (190, 145, "Approved"),
]:
    page.insert_text((x, y), text)
page = doc.new_page()
page.insert_text((50, 60), "Second page. Hosting provider: ExampleCloud. Region: west.")
doc.save(sys.argv[1])
doc.close()
