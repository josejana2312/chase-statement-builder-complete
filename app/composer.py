#!/usr/bin/env python3
"""Dynamic Statement Builder composer — chrome clips + engine body."""
from __future__ import annotations

from pathlib import Path
ASSETS = Path(__file__).resolve().parent / "assets"
import pymupdf as fitz

ROOT = Path("/home/workdir/artifacts")
SRC_PDF = Path("/home/workdir/attachments/Chase Statement.pdf")
REG = str(ROOT / "fonts/xenos/Helvetica.ttf")
BOLD = str(ROOT / "fonts/xenos/Helvetica-Bold.ttf")
OBLIQUE = str(ROOT / "fonts/xenos/Helvetica-Oblique.ttf")
ARIALB = str(ROOT / "fonts/xenos/Arial-BoldMT.otf")

W, H = 612.0, 792.0
COL_DATE, COL_DESC, COL_DESC_CARD = 33.6, 83.78, 83.78
DESC_RIGHT, AMT_RIGHT = 444.0, 532.0
SUM_AMT_RIGHT, SUM_AMT_HEAD = 375.80, 376.07
RULE_L, RULE_R = 31.6, 536.8
ROW, LEAD = 13.2, 10.33
FLOOR, FOOTER_Y = 765.0, 768.5  # page# 768.5; min last-txn gap ~17 → last 751.5; FLOOR=last+13.2
# Measured from private/Chase Statement.pdf page 1:
#   IMB image bbox x0=48.30; routing/sort text origin x=48.26.
# Align customer block to that common left edge (was 46.4).
NAME_X, NAME_MAX_W = 48.26, 196.14  # stop before IMB (~245)
SORT_LINE_X, SORT_LINE_Y = 48.26, 141.80
NAME_Y_DEFAULT = 154.30
IMB_TOP_Y = 122.20
SORT_TO_NAME = NAME_Y_DEFAULT - SORT_LINE_Y  # 12.50
IMB_TO_SORT = SORT_LINE_Y - IMB_TOP_Y        # 19.60
CANONICAL_SORT_LINE = "00XXXXXX DRE 021 210 XXXXX NNNNNNNNNNN 1 000000000 6X 0000"

_src = None


def src_doc():
    global _src
    if _src is None:
        _src = fitz.open(str(SRC_PDF))
    return _src


def face(bold=False, arial=False, italic=False):
    if arial:
        return fitz.Font(fontfile=ARIALB)
    if italic:
        return fitz.Font(fontfile=OBLIQUE)
    return fitz.Font(fontfile=BOLD if bold else REG)


def put(page, s, x, y, size=9, bold=False, arial=False, align="left", italic=False):
    if s is None or s == "":
        return
    f = face(bold, arial, italic)
    if align == "right":
        x = x - f.text_length(str(s), fontsize=size)
    twr = fitz.TextWriter(page.rect)
    twr.append(fitz.Point(x, y), str(s), font=f, fontsize=size)
    twr.write_text(page)


def draw_runs(page, x, y, runs):
    """Sequential mixed-style runs on one baseline. Returns x after last glyph."""
    for text, size, bold in runs:
        if not text:
            continue
        f = face(bold=bold)
        twr = fitz.TextWriter(page.rect)
        twr.append(fitz.Point(x, y), str(text), font=f, fontsize=size)
        twr.write_text(page)
        x += f.text_length(str(text), fontsize=size)
    return x


def tw(s, size=9, bold=False, arial=False, italic=False):
    return face(bold, arial, italic).text_length(str(s), fontsize=size)


def line(page, x0, y0, x1, y1, w=0.72):
    sh = page.new_shape()
    sh.draw_line(fitz.Point(x0, y0), fitz.Point(x1, y1))
    sh.finish(color=(0, 0, 0), width=w)
    sh.commit()


def box(page, x0, y0, x1, y1, w=0.72):
    sh = page.new_shape()
    sh.draw_rect(fitz.Rect(x0, y0, x1, y1))
    sh.finish(color=(0, 0, 0), width=w)
    sh.commit()


def money(n, dollar=False):
    n = float(n)
    sign = "-" if n < 0 else ""
    body = f"{abs(n):,.2f}"
    if dollar:
        return f"{sign}${body}"
    return f"- {body}" if n < 0 else body


def wrap(text, size, maxw, bold=False):
    f = face(bold)
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        trial = w if not cur else f"{cur} {w}"
        if f.text_length(trial, fontsize=size) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        if f.text_length(ln, fontsize=size) <= maxw:
            out.append(ln)
            continue
        buf = ""
        for ch in ln:
            if f.text_length(buf + ch, fontsize=size) <= maxw or not buf:
                buf += ch
            else:
                out.append(buf)
                buf = ch
        if buf:
            out.append(buf)
    return out or [""]


def clip_images(dest, src_i, regions):
    page = src_doc()[src_i]
    for info in page.get_image_info():
        r = fitz.Rect(info["bbox"])
        c = fitz.Point(r.x0 + r.width / 2, r.y0 + r.height / 2)
        if any(fitz.Rect(a).contains(c) for a in regions):
            # never show_pdf_page a source page that also contains VBAR/UR
            # unless the region is logo-sized on p1/p2
            if r.width < 40 and r.height > 80:
                continue
            try:
                dest.show_pdf_page(r, src_doc(), src_i, clip=r)
            except Exception:
                pass

def stamp_vbar(page, show=True):
    if not show:
        return
    img = ASSETS / "vbar.png"
    if img.exists():
        page.insert_image(fitz.Rect(569.8, 145.2, 598.6, 252.0), filename=str(img))

def stamp_ur(page, title_base):
    img = ASSETS / "ur-logo.png"
    top = title_base - 11.8
    if img.exists():
        page.insert_image(fitz.Rect(413.0, top, 524.9, top + 34.8), filename=str(img))


LOGO = (40, 32, 160, 70)
IMB = (40, 115, 260, 140)
VBAR = (560, 130, 612, 270)
HOUSING = (260, 670, 310, 720)
P2_LOGO = (60, 40, 160, 70)
UNDER = (20, 35, 160, 42)


def stamp_first(page, data=None):
    data = data or {}
    show_imb = data.get("show_imb", True)
    show_sort = data.get("show_sort_line", True)
    show_vbar = data.get("show_vbar", True)
    regions = [LOGO, UNDER]
    if show_imb:
        regions.append(IMB)
    clip_images(page, 0, regions)
    stamp_vbar(page, show_vbar)
    put(page, "JPMorgan Chase Bank, N.A.", 49.80, 66.20, 7.76)
    put(page, "P O Box 659754", 49.80, 75.40, 7.76)
    put(page, "San Antonio, TX 78265 - 9754", 49.80, 84.50, 7.76)
    sort_y = SORT_LINE_Y if show_imb else (SORT_LINE_Y - IMB_TO_SORT)
    if show_sort:
        put(page, data.get("sort_line") or CANONICAL_SORT_LINE, SORT_LINE_X, sort_y, 7.0)
    line(page, 338.70, 87.20, 522.80, 87.20, 2.16)
    line(page, 338.70, 106.20, 522.80, 106.20, 2.16)
    put(page, "CUSTOMER SERVICE INFORMATION", 341.10, 100.10, 10, bold=True)
    pairs = [
        (116.20, "Web site:", "Chase.com"),
        (127.40, "Service Center:", "1-800-242-7338"),
        (138.20, "Hearing Impaired:", "1-800-242-7383"),
        (149.00, "Para Espanol:", "1-888-622-4273"),
        (159.80, "International Calls:", "1-713-262-1679"),
    ]
    for y, lab, val in pairs:
        put(page, lab, 340.20, y, 9)
        put(page, val, 520.62, y, 9, align="right")


SERVICE_BOX_L, SERVICE_BOX_R = 338.70, 522.80
SERVICE_CENTER_X = (SERVICE_BOX_L + SERVICE_BOX_R) / 2.0  # 430.75


def period_account(page, period, account, compact=False):
    """First page: center period and 'Primary Account:'+number on CSI box center."""
    if compact:
        # Approved Primary Account placement is the reference axis.
        label = "Primary Account:"
        acct_s = str(account)
        put(page, label, 369.10, 67.00, 7.76)
        put(page, acct_s, 431.88, 67.00, 10, bold=True)
        group_l = 369.10
        group_r = 431.88 + tw(acct_s, 10, bold=True)
        center = (group_l + group_r) / 2.0
        period_s = str(period)
        pw = tw(period_s, 7.76)
        put(page, period_s, center - pw / 2.0, 54.00, 7.76)
        return
    period = str(period)
    account = str(account)
    pw = tw(period, 7.76)
    put(page, period, SERVICE_CENTER_X - pw / 2.0, 59.00, 7.76)
    label = "Primary Account:"
    gap = 3.70
    lw = tw(label, 7.76)
    aw = tw(account, 10, bold=True)
    total = lw + gap + aw
    sx = SERVICE_CENTER_X - total / 2.0
    put(page, label, sx, 72.00, 7.76)
    put(page, account, sx + lw + gap, 72.00, 10, bold=True)


def title_band(page, title, y_top, continued=False):
    """Xenos: boxed title + hairline; '(continued)' to the right of the box."""
    text_w = tw(title.strip(), 14, bold=True)
    # Xenos: left pad ~3, right pad ~4 on short titles, ~2 on long
    pad_l, pad_r = 3.1, (4.0 if text_w < 170 else 2.0)
    box_h = 17.8
    x0 = 35.25 if title.startswith("CHECKING SUMMARY") else (30.0 if continued or y_top < 120 else 33.1)
    x1 = x0 + text_w + pad_l + pad_r
    box(page, x0, y_top, x1, y_top + box_h)
    # Rewards header rule stops before UR artwork (Xenos p8 x2=409.60)
    rule_r = 409.60 if "REWARDS" in title else RULE_R
    # Rule is independent of (continued) width. Xenos p9: rule 189.1–410.6
    # under the oblique label; start just after the title box (~x1+3).
    rule_l = x1 + (3.0 if continued else 0.0)
    line(page, rule_l, y_top + 14.8 if continued else y_top + 13.8, rule_r, y_top + 14.8 if continued else y_top + 13.8)
    put(page, title.strip(), x0 + pad_l, y_top + 13.2, 14, bold=True)
    if continued:
        put(page, "(continued)", x1 + 4.3, y_top + 8.4, 9, italic=True)
    # DATE header sits 31.0 below box top on Xenos continuation (124.40-93.40)
    return y_top + 31.0


def col_headers(page, y, desc_x=COL_DESC):
    put(page, "DATE", COL_DATE, y, 7)
    put(page, "DESCRIPTION", desc_x, y, 7)
    put(page, "AMOUNT", AMT_RIGHT, y, 7, align="right")
    return y + 11.7


class Engine:
    def __init__(self, doc, period, account, data=None):
        self.doc = doc
        self.period = period
        self.account = account
        self.data = data or {}
        self.kinds = []

    def first(self):
        p = self.doc.new_page(width=W, height=H)
        stamp_first(p, self.data)
        period_account(p, self.period, self.account, False)
        self.kinds.append("first")
        return p

    def _page_no(self):
        return len(self.doc)

    def cont(self):
        p = self.doc.new_page(width=W, height=H)
        period_account(p, self.period, self.account, True)
        self.kinds.append("cont")
        return p

    def legal(self):
        p = self.doc.new_page(width=W, height=H)
        clip_images(p, 1, [P2_LOGO, HOUSING])
        period_account(p, self.period, self.account, True)
        self.kinds.append("legal")
        return p

    def savings(self):
        p = self.doc.new_page(width=W, height=H)
        period_account(p, self.period, self.account, True)
        self.kinds.append("savings")
        return p


def section(eng, page, y, title, rows, desc_x=COL_DESC):
    def start(p, yy, cont=False):
        yy = title_band(p, title, yy, continued=cont)
        if title.startswith("CHECKS"):
            put(p, "CHECK NO.", 31.0, yy, 7)
            put(p, "DESCRIPTION", 112.0, yy, 7)
            put(p, "DATE PAID", 427.0, yy, 7)
            put(p, "AMOUNT", AMT_RIGHT, yy, 7, align="right")
            yy += 20.6  # Xenos DATE→row plus extra header band
        else:
            yy = col_headers(p, yy, desc_x)
        return p, yy

    header_need = 20 + 14 + 14 + ROW
    if y + header_need > FLOOR:
        page = eng.cont()
        y = 93.4
    page, y = start(page, y, False)

    if not rows:
        # Visible empty: heading + columns already drawn; blank body; Total $0.00.
        line(page, RULE_L, y + 4, RULE_R, y + 4)
        put(page, "Total " + title.title().replace(" And "," and ").replace("Atm","ATM"), COL_DATE, y + 16, 9, bold=True)
        put(page, money(0, True), AMT_RIGHT, y + 16, 9, bold=True, align="right")
        extra = 1.2 if title.startswith("ATM") else 0.0
        if title.startswith("ELECTRONIC"):
            return page, y + 18.0
        if title.startswith("CHECKS"):
            return page, y + 28.0
        return page, y + 26.4 + extra

    total = 0.0
    for r in rows:
        if isinstance(r.get("lines"), list) and r["lines"]:
            lines = list(r["lines"])
        else:
            lines = wrap(r["desc"], 9, DESC_RIGHT - desc_x)
        n = len(lines)
        last_base = y if n == 1 else y + (n - 1) * LEAD
        rule_y = last_base + 4.0
        block_h = (rule_y - y) + 9.2
        if y + block_h > FLOOR:
            page = eng.cont()
            y = 93.4
            page, y = start(page, y, True)
            last_base = y if n == 1 else y + (n - 1) * LEAD
            rule_y = last_base + 4.0
            block_h = (rule_y - y) + 9.2
        if title.startswith("CHECKS"):
            put(page, r.get("check_no") or lines[0].split()[-1] if False else (r.get("check_no") or r.get("desc","")[:6]), 31.0, y, 9)
            put(page, r["date"], 427.0, y, 9)
            put(page, money(r["amount"]), AMT_RIGHT, y, 9, align="right")
            put(page, r.get("desc",""), 112.0, y, 9)
        else:
            put(page, r["date"], COL_DATE, y, 9)
            put(page, money(r["amount"]), AMT_RIGHT, y, 9, align="right")
        yy = y
        if not title.startswith("CHECKS"):
          for ln in lines:
            put(page, ln, desc_x, yy, 9)
            yy += LEAD if n > 1 else 0
        line(page, RULE_L, rule_y, RULE_R, rule_y)
        y = rule_y + 9.2
        total += float(r["amount"])

    if y + 18 > FLOOR:
        page = eng.cont()
        y = 93.4
        page, y = start(page, y, True)
    if title.startswith("ATM") or title.startswith("ELECTRONIC"):
        y += 2.2  # last→total 15.4
    put(page, "Total " + (title[:1]+title[1:].lower() if False else title.replace(" AND "," and ").title().replace("Atm","ATM").replace("Debit Card","Debit Card")), COL_DATE, y, 9, bold=True)
    put(page, money(total, True), AMT_RIGHT, y, 9, bold=True, align="right")
    if title.startswith("CHECKS"):
        y += 17.5
        put(page, "If you see a description in the Checks Paid section, it means that we received only electronic information about the check,", 33.6, y, 8)
        put(page, "not the original or an image of the check. As a result, we're not able to return the check to you or show you an image.", 33.6, y+8.2, 8)
        put(page, "^ An image of this check may be available for you to view on Chase.com.", 33.6, y+38.2, 8)
        # Xenos: caret 596.7 → ATM title box top 616.7 (+20)
        y = y + 38.2 + 24.6
        return page, y
    extra = 1.2 if title.startswith("ATM") else 0.0
    if title.startswith("ELECTRONIC"):
        return page, y + 18.0  # Xenos total→fees title 31.2
    return page, y + 26.4 + extra


# Legal unit: DEMO page-2 typography + explicit v3 styling (rules, right FDIC group).
LEGAL_LEFT = 41.90
LEGAL_INFO_X = 84.93
LEGAL_HEAD = 7.00
LEGAL_BODY = 7.76
LEGAL_FIRST_BASE = 550.00
EFT_HEAD = "IN CASE OF ERRORS OR QUESTIONS ABOUT YOUR ELECTRONIC FUNDS TRANSFERS:"
NONEFT_HEAD = "IN CASE OF ERRORS OR QUESTIONS ABOUT NON-ELECTRONIC TRANSACTIONS:"
FDIC_TEXT = "JPMorgan Chase Bank, N.A. Member FDIC"
HOUSING_SRC = fitz.Rect(276.16, 682.96, 296.32, 706.48)
HOUSING_W, HOUSING_H = 20.16, 23.52
ICON_TEXT_GAP = 8.0
FDIC_Y, FDIC_SIZE = 706.80, 8.00
TOP_RULE_Y = 538.00
# bottom rule computed after icon; nominal values used for fit height
BOTTOM_RULE_Y = 722.00
LEGAL_TOP = TOP_RULE_Y
LEGAL_CONTENT_BOTTOM = BOTTOM_RULE_Y
LEGAL_GAP = 12.0


def stamp_housing(page, dest):
    page.show_pdf_page(dest, src_doc(), 1, clip=HOUSING_SRC)


def stamp_legal(page, bottom=None) -> float:
    """Draw legal unit: rules + DEMO wording + right-aligned housing/FDIC group."""
    line(page, RULE_L, TOP_RULE_Y, RULE_R, TOP_RULE_Y, 0.72)
    draw_runs(page, LEGAL_LEFT, 550.00, [
        (EFT_HEAD, LEGAL_HEAD, True),
        (" ", LEGAL_BODY, False),
        ("Call or write us at the phone number or address on", LEGAL_BODY, False),
    ])
    put(page, "the front of this statement (non-personal accounts contact Customer Service) if you think your statement or receipt is incorrect or if you", LEGAL_LEFT, 558.20, LEGAL_BODY)
    put(page, "need more information about a transfer listed on the statement or receipt. We must hear from you no later than 60 days after we sent you", LEGAL_LEFT, 566.10, LEGAL_BODY)
    put(page, "the FIRST statement on which the problem or error appeared.  Be prepared to give us the following information:", LEGAL_LEFT, 574.00, LEGAL_BODY)
    put(page, "Your name and account number", LEGAL_INFO_X, 582.00, LEGAL_BODY)
    put(page, "The dollar amount of the suspected error", LEGAL_INFO_X, 589.90, LEGAL_BODY)
    put(page, "A description of the error or transfer you are unsure of, why you believe it is an error, or why you need more information.", LEGAL_INFO_X, 597.80, LEGAL_BODY)
    put(page, "We will investigate your complaint and will correct any error promptly.  If we take more than 10 business days (or 20 business days for", LEGAL_LEFT, 605.70, LEGAL_BODY)
    put(page, "new accounts) to do this, we will credit your account for the amount you think is in error so that you will have use of the money during the", LEGAL_LEFT, 613.60, LEGAL_BODY)
    put(page, "time it takes us to complete our investigation.", LEGAL_LEFT, 621.60, LEGAL_BODY)
    draw_runs(page, LEGAL_LEFT, 637.40, [
        (NONEFT_HEAD, LEGAL_HEAD, True),
        (" ", LEGAL_BODY, False),
        ("Contact the bank immediately if your statement is", LEGAL_BODY, False),
    ])
    put(page, "incorrect or if you need more information about any non-electronic transactions (checks or deposits) on this statement. If any such error", LEGAL_LEFT, 645.60, LEGAL_BODY)
    put(page, "appears, you must notify the bank in writing no later than 30 days after the statement was made available to you. For more complete", LEGAL_LEFT, 653.50, LEGAL_BODY)
    put(page, "details, see the Account Rules and Regulations or other applicable account agreement that governs your account.", LEGAL_LEFT, 661.40, LEGAL_BODY)

    fdic_w = face(True).text_length(FDIC_TEXT, FDIC_SIZE)
    fdic_x = RULE_R - fdic_w
    put(page, FDIC_TEXT, fdic_x, FDIC_Y, FDIC_SIZE, bold=True)
    # Optical center of FDIC line vs icon center.
    text_cy = FDIC_Y - FDIC_SIZE * 0.35
    icon_y0 = text_cy - HOUSING_H / 2.0
    icon_x = fdic_x - ICON_TEXT_GAP - HOUSING_W
    dest = fitz.Rect(icon_x, icon_y0, icon_x + HOUSING_W, icon_y0 + HOUSING_H)
    try:
        stamp_housing(page, dest)
    except Exception:
        pass
    bot = max(icon_y0 + HOUSING_H, FDIC_Y + 2.0) + 6.0
    line(page, RULE_L, bot, RULE_R, bot, 0.72)
    return LEGAL_TOP


def legal_unit_height() -> float:
    text_cy = FDIC_Y - FDIC_SIZE * 0.35
    icon_y1 = text_cy - HOUSING_H / 2.0 + HOUSING_H
    bot = max(icon_y1, FDIC_Y + 2.0) + 6.0
    return bot - TOP_RULE_Y


def compose(data: dict, dest: Path | str) -> Path:
    dest = Path(dest)
    doc = fitz.open()
    eng = Engine(doc, data["period"], data["account"], data)
    p = eng.first()

    # customer name wrap in reserved column — reflow only this stack
    show_imb = data.get("show_imb", True)
    show_sort = data.get("show_sort_line", True)
    y_name = NAME_Y_DEFAULT
    if not show_imb:
        y_name -= IMB_TO_SORT
    if not show_sort:
        y_name -= SORT_TO_NAME
    name_lines = wrap(data.get("name", ""), 9, NAME_MAX_W)
    for ln in name_lines[:3]:
        put(p, ln, NAME_X, y_name, 9)
        y_name += 10.4
    put(p, data.get("addr", ""), NAME_X, y_name, 9)
    put(p, data.get("city", ""), NAME_X, y_name + 10.4, 9)

    y = y_name + 10.4 + 16.0
    show_summary = data.get("show_summary", True)
    secs = data["sections"]
    opening = float(data["opening"])
    counts = [len(s.get("rows") or []) for s in secs]
    totals = []
    for s in secs:
        sgn = s.get("sign", 1)
        totals.append(sgn * sum(float(r["amount"]) for r in s.get("rows") or []))
    ending = opening + sum(totals)
    inst_end = sum(counts)
    labels = [
        ("Beginning Balance", None, opening, True, True),
        (secs[0].get("summary_label") or "Deposits and Additions", counts[0], totals[0], False, True),
        (secs[1].get("summary_label") or "Checks Paid", counts[1], totals[1], False, False),
        (secs[2].get("summary_label") or "ATM & Debit Card Withdrawals", counts[2], totals[2], False, False),
        (secs[3].get("summary_label") or "Electronic Withdrawals", counts[3], totals[3], False, False),
        (secs[4].get("summary_label") or "Fees and Other Withdrawals", counts[4], totals[4], False, False),
        ("Ending Balance", inst_end, ending, True, True),
    ]
    if show_summary:
        if y < 230.28:
            y = 230.28
        y = title_band(p, "CHECKING SUMMARY", y)
        sum_head_y = y + 11.50
        put(p, "INSTANCES", 258.60, sum_head_y, 7, align="right")
        put(p, "AMOUNT", SUM_AMT_HEAD, sum_head_y, 7, align="right")
        y = sum_head_y + 11.50
        for i, (lab, inst, amt, bld, dol) in enumerate(labels):
            put(p, lab, 36, y, 9, bold=bld, arial=bld)
            if inst is not None:
                put(p, str(inst), 258.60, y, 9, bold=bld, arial=bld, align="right")
            put(p, money(amt, dol), SUM_AMT_RIGHT, y, 9, bold=bld, arial=bld, align="right")
            if lab == "Fees and Other Withdrawals" or lab.lower().startswith("fees"):
                line(p, 204.05, y + 4.90, 377.75, y + 4.90)
            pitches = [13.70, 13.20, 14.40, 14.40, 14.40, 14.40]
            if i < len(pitches):
                y += pitches[i]
        y += 35.32

    FEE1_DEFAULT = (
        "Your monthly service fee was waived because you maintained an average checking balance of $7,500.00 or a minimum "
        "checking balance of $5,000.00 or more during the statement period."
    )
    FEE2_DEFAULT = (
        "The monthly service fee for this account was waived as an added feature of Chase BusinessSelect Checking account."
    )
    if data.get("show_fee_notice_1", True):
        t1 = (data.get("fee_notice_1") or FEE1_DEFAULT).strip() or FEE1_DEFAULT
        for ln in wrap(t1, 9, 500):
            if y + 12 > FLOOR:
                p = eng.cont(); y = 93.4
            put(p, ln, 35.20, y, 9)
            y += 10.3
        y += 6.0
    if data.get("show_fee_notice_2", True):
        t2 = (data.get("fee_notice_2") or FEE2_DEFAULT).strip() or FEE2_DEFAULT
        for ln in wrap(t2, 9, 500):
            if y + 12 > FLOOR:
                p = eng.cont(); y = 93.4
            put(p, ln, 35.20, y, 9)
            y += 10.3
        y += 6.7

    for sec in secs:
        if sec.get("omit"):
            continue
        rows = sec.get("rows") or []
        dx = COL_DESC_CARD if sec.get("card") else COL_DESC
        p, y = section(eng, p, y, sec["title"], rows, desc_x=dx)

    if data.get("show_notices", True):
        for note in data.get("notices") or []:
            for ln in wrap(note, 7.76, 500):
                if y + 12 > FLOOR:
                    p = eng.cont(); y = 93.4
                put(p, ln, 32.10, y, 7.76)
                y += 10.3

    # rewards — fragment pagination (Xenos p8 title 677.8, DATE 699.2, first 711.6)
    rw = data.get("rewards")
    if rw:
        # min fragment: title 17.8 + DATE 21.4 + first row 12.4 ≈ 52
        if y + 52 > FLOOR:
            p = eng.cont(); y = 93.4
        if rw.get("card"):
            put(p, rw["card"], 193.60, y + 8.8, 9)  # same band as title (Xenos 673 vs title 677.8)
        y = title_band(p, rw.get("title") or "REWARDS SUMMARY", y)
        stamp_ur(p, y - 31.0 + 13.2)
        put(p, "DATE", COL_DATE, y, 7)
        put(p, "DESCRIPTION", 83.70, y, 7)
        y += 12.4
        first_date = rw.get("date") or "09/30"
        body = []
        for ln in rw.get("lines") or []:
            if rw.get("prewrapped"):
                body.append(ln)
            else:
                body.extend(wrap(ln, 9, 360))
        # first content unit includes date on first line
        if body:
            put(p, first_date, COL_DATE, y, 9)
            put(p, body[0], 83.70, y, 9)
            y += 13.2
            for wln in body[1:]:
                extra = 13.2 if wln.startswith("Visit") else 0.0
                if y + 14 + extra > FLOOR:
                    p = eng.cont(); y = 93.4
                    y = title_band(p, rw.get("title") or "REWARDS SUMMARY", y, continued=True)
                    stamp_ur(p, y - 31.0 + 13.2)
                    y += 7.4  # Xenos continued title 107.1 → first line 132.3
                y += extra
                put(p, wln, 83.70, y, 9)
                y += 13.2
        if rw.get("points_label") or rw.get("points") is not None:
            if y + 26 > FLOOR:
                p = eng.cont(); y = 93.4
                y = title_band(p, rw.get("title") or "REWARDS SUMMARY", y, continued=True)
                stamp_ur(p, y - 31.0 + 13.2)
                y += 7.4
            y += 13.2
            put(p, rw.get("points_label") or "Debit Card ending 3298 - Total points balance as of 08/24/20", 83.70, y, 9)
            put(p, str(rw.get("points", 0)), AMT_RIGHT, y, 9, align="right")
            y += 10.4

    # daily ending balances
    deb = data.get("daily_balances") or []
    if deb:
        if y + 40 > FLOOR:
            p = eng.cont(); y = 95
        y = title_band(p, "DAILY ENDING BALANCE", y)
        # Xenos: L DATE 33.6, L AMT right 214.6, R DATE 351.1/351.8, R AMT right 532.9
        put(p, "DATE", 33.60, y, 7)
        put(p, "AMOUNT", 214.52, y, 7, align="right")
        put(p, "DATE", 351.10, y, 7)
        put(p, "AMOUNT", 533.02, y, 7, align="right")
        y += 14.4
        mid = (len(deb) + 1) // 2
        left, right = deb[:mid], deb[mid:]
        for i in range(max(len(left), len(right))):
            if y + 16.8 > FLOOR:
                p = eng.cont(); y = 95
                y = title_band(p, "DAILY ENDING BALANCE", y, continued=True)
            if i < len(left):
                put(p, left[i]["date"], 33.60, y, 9)
                put(p, money(left[i]["amount"]), 214.59, y, 9, align="right")
            if i < len(right):
                put(p, right[i]["date"], 351.80, y, 9)
                put(p, money(right[i]["amount"]), 532.90, y, 9, align="right")
            y += 16.8
        y -= 3.0  # last-row advance already consumed; Xenos last 410 → service box 422.6

    # service charge summary
    sc = data.get("service_charge")
    if sc:
        if y + 90 > FLOOR:
            p = eng.cont(); y = 95
        y = title_band(p, "SERVICE CHARGE SUMMARY", y)
        SC_NUM, SC_AMT = 522.61, 522.32
        put(p, "TRANSACTIONS FOR SERVICE FEE CALCULATION", 33.6, y, 7, bold=True)
        put(p, "NUMBER OF TRANSACTIONS", SC_NUM, y, 7, bold=True, align="right")
        y += 12.5
        for lab, key, bld in [
            ("Checks Paid / Debits", "checks_debits", False),
            ("Deposits / Credits", "deposits_credits", False),
            ("Deposited Items", "deposited_items", False),
            ("Transaction Total", "transaction_total", True),
        ]:
            if key == "transaction_total":
                line(p, 456.0, y - 9.5, 524.4, y - 9.5)  # Xenos 495.3 above total
            put(p, lab, 33.6, y, 9, bold=bld)
            put(p, str(sc.get(key, 0)), SC_NUM, y, 9, bold=bld, align="right")
            y += 13.2
        y += 8.1
        put(p, "SERVICE FEE CALCULATION", 33.6, y, 7, bold=True)
        put(p, "AMOUNT", SC_AMT, y, 7, bold=True, align="right")
        y += 12.5
        # Xenos order: Fee, Credit, [rule] Net, Excessive, [rule] Total
        fee_rows = [
            ("Service Fee", "service_fee", True, False, False),
            ("Service Fee Credit", "service_fee_credit", True, False, True),
            ("Net Service Fee", "net_service_fee", True, True, False),
            ("Excessive Transaction Fees (Above 200)", "excessive_fees", True, False, True),
            ("Total Service Fees", "total_service_fees", True, True, False),
        ]
        for lab, key, dol, bld, rule_after in fee_rows:
            val = sc.get(key, 0)
            put(p, lab, 33.6, y, 9, bold=bld)
            put(p, money(val, dol), SC_AMT, y, 9, bold=bld, align="right")
            if rule_after:
                line(p, 456.0, y + 3.7, 524.4, y + 3.7)
            y += 13.2
        y += 16

    legal_h = legal_unit_height()
    if y + LEGAL_GAP <= LEGAL_TOP:
        stamp_legal(p)
    else:
        lp = eng.cont()
        stamp_legal(lp)

    show_vbar = data.get("show_vbar", True)
    for i in range(len(doc)):
        n = i + 1
        if n in (4, 6, 8, 10):
            stamp_vbar(doc[i], show_vbar)

    n = doc.page_count
    for i, pg in enumerate(doc):
        put(pg, f"Page {i+1} of {n}", 502.13, FOOTER_Y, 7, align="right")

    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dest), deflate=True)
    doc.close()
    return dest
