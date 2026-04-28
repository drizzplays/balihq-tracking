# PATCHED VERSION (zebra removed)
# Only showing relevant change for brevity in this generated file

# In draw_row function replace row background with uniform color:

def draw_row(draw, xs, y, row, idx, row_h, fonts):
    # UNIFORM ROW COLOR (no zebra)
    draw.rectangle((X0, y, X0 + TABLE_W, y + row_h), fill=(242, 250, 253, 235))

    lf, lt = league_style(row[0])
    bf, bt = bet_style(row[6])

    draw.rectangle((xs[0], y, xs[1], y + row_h), fill=lf)
    draw.rectangle((xs[6], y, xs[7], y + row_h), fill=bf)

    for j, xx in enumerate(xs):
        width = 2 if j in (0, 8, 9, len(xs) - 1) else 1
        draw.line((xx, y, xx, y + row_h), fill=GRID, width=width)

    draw.line((X0, y + row_h, X0 + TABLE_W, y + row_h), fill=GRID_SOFT, width=1)

    for i, c in enumerate(row):
        font = fonts["name"] if i in (4, 5) else fonts["body"]
        fill = lt if i == 0 else bt if i == 6 else TEXT
        value = str(c).upper() if i == 6 else c
        center_text(draw, (xs[i] + 2, y, xs[i + 1] - 2, y + row_h), value, font, fill, yoff=-1)
