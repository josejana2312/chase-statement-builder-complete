#!/usr/bin/env python3
"""Dynamic Statement Builder — staff dashboard. Composer POC v3 is the only renderer."""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
import sys
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from composer import compose  # Composer POC v3

app = FastAPI(title="Dynamic Statement Builder")
SESSION_ROOT = Path(os.environ.get("DSB_SESSION_DIR", "/tmp/dsb-sessions"))
SESSION_ROOT.mkdir(parents=True, exist_ok=True)


@app.middleware("http")
async def isolate_preview_session(request: Request, call_next):
    """One preview PDF per browser. Does not change Composer output."""
    sid = request.cookies.get("dsb_sid") or ""
    fresh = not re.fullmatch(r"[a-f0-9]{32}", sid)
    if fresh:
        sid = secrets.token_hex(16)
    folder = SESSION_ROOT / sid
    folder.mkdir(parents=True, exist_ok=True)
    request.state.sid = sid
    request.state.sess = folder
    response = await call_next(request)
    if fresh:
        response.set_cookie(
            "dsb_sid",
            sid,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return response


def _session_paths(request: Request):
    folder = request.state.sess
    return folder / "preview.pdf", folder / "last-ok.pdf"


FIXTURES = {
    "testA": HERE / "original.json",
    "testB": HERE / "synthetic.json",
    "testC": HERE / "synthetic.json",
    "testD": HERE / "test-d.json",
}

CANONICAL_SORT_LINE = "00XXXXXX DRE 021 210 XXXXX NNNNNNNNNNN 1 000000000 6X 0000"


def apply_sort_mask(value: str | None, *, fill_unresolved: bool = False) -> str:
    """Enforce the canonical sort-line mask.

    Non-X template positions are immutable literals.
    X positions may be an unresolved 'X' or a digit 0-9.
    When fill_unresolved is True, remaining X slots become synthetic digits.
    """
    raw = value if isinstance(value, str) else ""
    out = []
    for i, mask_ch in enumerate(CANONICAL_SORT_LINE):
        ch = raw[i] if i < len(raw) else mask_ch
        if mask_ch == "X":
            if ch in "0123456789":
                out.append(ch)
            elif fill_unresolved:
                out.append(str(secrets.randbelow(10)))
            else:
                out.append("X")
        else:
            out.append(mask_ch)
    return "".join(out)


def sort_line_has_unresolved(value: str | None) -> bool:
    return isinstance(value, str) and "X" in value


def validate_sort_line(value) -> list:
    """Reject malformed sort-line input. Do not pad, truncate, or shift."""
    if value is None or value == "":
        return []
    if not isinstance(value, str):
        return ["Routing/sort line must be the canonical synthetic template string."]
    if len(value) != len(CANONICAL_SORT_LINE):
        return ["Routing/sort line must be exactly the canonical synthetic template length; values are not padded, truncated, or shifted."]
    for i, mask_ch in enumerate(CANONICAL_SORT_LINE):
        ch = value[i]
        if mask_ch == "X":
            if ch not in "0123456789X":
                return ["Routing/sort line variable positions may contain only X or digits 0-9."]
        elif ch != mask_ch:
            return ["Routing/sort line static positions must match the canonical synthetic template exactly."]
    return []


FEE_NOTICE_1_DEFAULT = (
    "Your monthly service fee was waived because you maintained an average checking balance of $7,500.00 or a minimum "
    "checking balance of $5,000.00 or more during the statement period."
)
FEE_NOTICE_2_DEFAULT = (
    "The monthly service fee for this account was waived as an added feature of Chase BusinessSelect Checking account."
)
FEE_NOTICE_MAX = 600

CHROME_FLAG_DEFAULTS = {
    "show_vbar": True,
    "show_imb": True,
    "show_sort_line": True,
    "show_summary": True,
    "show_fee_notice_1": True,
    "show_fee_notice_2": True,
    "show_notices": True,
}


def default_flags(data: dict | None = None) -> dict:
    data = data or {}
    return {
        "rewards": bool(data.get("rewards")),
        "daily": bool(data.get("daily_balances")),
        "service": bool(data.get("service_charge")),
        "savings": bool(data.get("savings")),
        "excluded": [],
        **CHROME_FLAG_DEFAULTS,
    }


CHECKING_SLOTS = [
    {"id": "deposits", "title": "DEPOSITS AND ADDITIONS", "summary_label": "Deposits and Additions", "sign": 1, "card": False},
    {"id": "checks", "title": "CHECKS PAID", "summary_label": "Checks Paid", "sign": -1, "card": False},
    {"id": "cards", "title": "ATM & DEBIT CARD WITHDRAWALS", "summary_label": "ATM & Debit Card Withdrawals", "sign": -1, "card": True},
    {"id": "electronic", "title": "ELECTRONIC WITHDRAWALS", "summary_label": "Electronic Withdrawals", "sign": -1, "card": False},
    {"id": "fees", "title": "FEES AND OTHER WITHDRAWALS", "summary_label": "Fees and Other Withdrawals", "sign": -1, "card": False},
]


def load_fixture(key: str) -> dict:
    path = FIXTURES.get(key)
    if not path or not path.exists():
        raise HTTPException(404, "Unknown fixture")
    data = json.loads(path.read_text())
    if key == "testC":
        data = copy.deepcopy(data)
        data["name"] = "NORTH ATLANTIC HOLDINGS INTERNATIONAL GROUP LLC"
        data["account"] = "000987654321098"
        data["opening"] = 1234567.89
    return normalize(data)


def normalize(data: dict) -> dict:
    data = copy.deepcopy(data)
    secs = data.get("sections") or []
    out = []
    for i, spec in enumerate(CHECKING_SLOTS):
        src = secs[i] if i < len(secs) else {}
        rows = []
        for r in src.get("rows") or []:
            rows.append({"date": str(r.get("date", "")), "desc": str(r.get("desc", "")), "amount": r.get("amount", 0)})
        merged = {**spec, **{k: src[k] for k in src if k not in ("rows",)}, "rows": rows}
        merged["id"] = spec["id"]
        merged["title"] = spec["title"]
        merged["sign"] = spec["sign"]
        if spec["card"]:
            merged["card"] = True
        out.append(merged)
    data["sections"] = out
    for k in ("period", "account", "name", "addr", "city"):
        data.setdefault(k, "")
    data.setdefault("opening", 0)
    data.setdefault("blank_page", True)  # ignored by Composer v3; kept for JSON compat
    sl = data.get("sort_line")
    if sl is None or sl == "":
        data["sort_line"] = CANONICAL_SORT_LINE
    # Do not coerce wrong-length or mutated-literal values here. validate_sort_line rejects them.
    data.setdefault("fee_notice_1", FEE_NOTICE_1_DEFAULT)
    data.setdefault("fee_notice_2", FEE_NOTICE_2_DEFAULT)
    acct = str(data.get("account") or "").strip()
    if re.fullmatch(r"\d{1,15}", acct):
        data["account"] = acct.zfill(15)
    else:
        data["account"] = acct
    return data


def blank_model() -> dict:
    return normalize({
        "period": "", "account": "", "name": "", "addr": "", "city": "", "opening": 0,
        "sections": [{**s, "rows": []} for s in CHECKING_SLOTS],
        "savings": None, "rewards": None, "daily_balances": [], "service_charge": None,
        "notices": [], "blank_page": True,
    })


MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12}
MONTH_NAMES = ["","January","February","March","April","May","June","July","August","September","October","November","December"]


def parse_txn_calendar_date(raw: str, period_start: datetime | None, period_end: datetime | None):
    """Parse MM/DD or MM/DD/YYYY. Bare MM/DD uses period year(s). Returns (datetime|None, error|None)."""
    s = str(raw or "").strip()
    if not s:
        return None, "missing"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", s)
    if not m:
        return None, "malformed"
    month, day = int(m.group(1)), int(m.group(2))
    years = []
    if m.group(3):
        y = int(m.group(3))
        if y < 100:
            y += 2000
        years = [y]
    elif period_start and period_end:
        years = sorted({period_start.year, period_end.year})
    else:
        return None, "malformed"
    parsed = []
    for y in years:
        try:
            parsed.append(datetime(y, month, day))
        except ValueError:
            continue
    if not parsed:
        return None, "malformed"
    if period_start and period_end:
        in_range = [d for d in parsed if period_start.date() <= d.date() <= period_end.date()]
        if not in_range:
            return None, "out_of_period"
        return in_range[0], None
    return parsed[0], None


def parse_period(period: str):
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s+through\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", period or "", re.I)
    if not m:
        return None, None
    a = datetime(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    b = datetime(int(m.group(6)), MONTHS[m.group(4).lower()], int(m.group(5)))
    return a, b


def format_period(a: datetime, b: datetime) -> str:
    return f"{MONTH_NAMES[a.month]} {a.day:02d}, {a.year} through {MONTH_NAMES[b.month]} {b.day:02d}, {b.year}"


def validate_model(data: dict) -> list:
    errs = []
    if not str(data.get("name") or "").strip():
        errs.append("Customer / business name is required.")
    acct = str(data.get("account") or "").strip()
    if not acct:
        errs.append("Primary account is required.")
    elif not re.fullmatch(r"\d+", acct):
        errs.append("Primary account must contain only digits (15 digits after left-padding).")
    elif len(acct) > 15:
        errs.append("Primary account must be at most 15 digits. Longer values are not truncated.")
    for key, label in (("fee_notice_1", "Fee notice 1"), ("fee_notice_2", "Fee notice 2")):
        if len(str(data.get(key) or "")) > FEE_NOTICE_MAX:
            errs.append(f"{label} must be at most {FEE_NOTICE_MAX} characters.")
    a, b = parse_period(str(data.get("period") or ""))
    if not a or not b:
        errs.append("Statement period must use valid calendar dates (Month DD, YYYY through Month DD, YYYY).")
    elif a > b:
        errs.append("Period start must be on or before period end.")
    try:
        float(data.get("opening", 0))
    except (TypeError, ValueError):
        errs.append("Opening balance must be numeric.")
    errs.extend(validate_sort_line(data.get("sort_line")))
    secs = data.get("sections")
    if not isinstance(secs, list) or len(secs) < 5:
        errs.append("Checking model must contain the five standard section slots.")
        return errs
    for s in secs:
        if not isinstance(s, dict):
            errs.append("Malformed section object.")
            continue
        for i, r in enumerate(s.get("rows") or []):
            if not isinstance(r, dict):
                errs.append(f"{s.get('title','Section')}: transaction {i+1} is malformed.")
                continue
            raw_date = str(r.get("date") or "").strip()
            if not raw_date:
                errs.append(f"{s.get('title','Section')}: transaction {i+1} needs a date.")
            elif a and b:
                _dt, derr = parse_txn_calendar_date(raw_date, a, b)
                if derr == "malformed":
                    errs.append(f"{s.get('title','Section')}: transaction {i+1} date '{raw_date}' is not a valid calendar date (use MM/DD or MM/DD/YYYY).")
                elif derr == "out_of_period":
                    errs.append(f"{s.get('title','Section')}: transaction {i+1} date '{raw_date}' is outside the statement period.")
            if not str(r.get("desc") or "").strip():
                errs.append(f"{s.get('title','Section')}: transaction {i+1} needs a description.")
            try:
                amt = float(r.get("amount"))
            except (TypeError, ValueError):
                errs.append(f"{s.get('title','Section')}: transaction {i+1} amount must be numeric.")
            else:
                if amt < 0:
                    errs.append(
                        f"{s.get('title','Section')}: transaction {i+1} amount must be a non-negative magnitude. "
                        "Direction comes from the section (deposits add; checks/cards/electronic/fees subtract)."
                    )
    sav = data.get("savings")
    if sav:
        try:
            float(sav.get("opening", 0))
        except (TypeError, ValueError):
            errs.append("Savings opening balance must be numeric.")
        for i, r in enumerate(sav.get("rows") or []):
            try:
                float(r.get("amount"))
            except (TypeError, ValueError):
                errs.append(f"Savings transaction {i+1} amount must be numeric.")
    return errs


def _parse_txn_date(raw: str):
    s = str(raw or "").strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", s)
    if not m:
        return None, s
    month, day = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else 0
    if year and year < 100:
        year += 2000
    return (year or 0, month, day), f"{month:02d}/{day:02d}"


def derive_daily_balances(data: dict) -> list:
    """Activity-day running balance from opening + signed section rows."""
    opening = float(data.get("opening") or 0)
    by_day = {}
    for sec in data.get("sections") or []:
        sign = float(sec.get("sign", 1))
        for r in sec.get("rows") or []:
            key, label = _parse_txn_date(r.get("date"))
            if key is None:
                key = (0, 0, 0)
                label = str(r.get("date") or "").strip() or "—"
            by_day.setdefault(key, {"date": label, "net": 0.0})
            by_day[key]["net"] += sign * float(r.get("amount") or 0)
    if not by_day:
        period = str(data.get("period") or "")
        a, _b = parse_period(period)
        label = f"{a.month:02d}/{a.day:02d}" if a else "—"
        return [{"date": label, "amount": opening}]
    running = opening
    out = []
    for key in sorted(by_day):
        running += by_day[key]["net"]
        out.append({"date": by_day[key]["date"], "amount": running})
    return out


def derive_service_charge(data: dict) -> dict:
    """Counts from included rows; monetary schedule fields stay explicit."""
    prev = data.get("service_charge") if isinstance(data.get("service_charge"), dict) else {}
    secs = data.get("sections") or []
    counts = [len((secs[i].get("rows") or []) if i < len(secs) else []) for i in range(5)]
    deposits_credits = counts[0]
    checks_debits = counts[1] + counts[2] + counts[3] + counts[4]
    try:
        deposited_items = int(prev.get("deposited_items") or 0)
    except (TypeError, ValueError):
        deposited_items = 0
    try:
        service_fee = float(prev.get("service_fee") or 0)
    except (TypeError, ValueError):
        service_fee = 0.0
    try:
        service_fee_credit = float(prev.get("service_fee_credit") or 0)
    except (TypeError, ValueError):
        service_fee_credit = 0.0
    try:
        excessive_fees = float(prev.get("excessive_fees") or 0)
    except (TypeError, ValueError):
        excessive_fees = 0.0
    net = service_fee + service_fee_credit
    return {
        "checks_debits": checks_debits,
        "deposits_credits": deposits_credits,
        "deposited_items": deposited_items,
        "transaction_total": checks_debits + deposits_credits + deposited_items,
        "service_fee": service_fee,
        "service_fee_credit": service_fee_credit,
        "net_service_fee": net,
        "excessive_fees": excessive_fees,
        "total_service_fees": net + excessive_fees,
    }


def summary_from(data: dict) -> dict:
    opening = float(data.get("opening") or 0)
    secs = data.get("sections") or []
    t = [0.0]*5; c=[0]*5
    for i in range(min(5,len(secs))):
        rows = secs[i].get("rows") or []
        c[i] = len(rows)
        t[i] = sum(float(r.get("amount") or 0) for r in rows)
    deposits, withdrawals = t[0], t[1]+t[2]+t[3]+t[4]
    ending = opening + deposits - withdrawals
    sav_end = None
    if data.get("savings"):
        sav_end = float(data["savings"].get("opening") or 0)
        for r in data["savings"].get("rows") or []:
            sav_end += float(r.get("amount") or 0)
    return {"opening":opening,"deposits":deposits,"withdrawals":withdrawals,"fees":t[4],"instances":sum(c),"ending":ending,"savings_ending":sav_end,"counts":{"deposits":c[0],"checks":c[1],"cards":c[2],"electronic":c[3],"fees":c[4]}}


def compose_payload(data: dict) -> dict:
    payload = copy.deepcopy(data)
    flags = payload.pop("_flags", {}) or {}
    if flags.get("rewards") is False:
        payload["rewards"] = None
    if flags.get("daily") is False:
        payload["daily_balances"] = []
    if flags.get("service") is False:
        payload["service_charge"] = None
    if flags.get("savings") is False:
        payload["savings"] = None
    excluded = flags.get("excluded") or []
    for i, spec in enumerate(CHECKING_SLOTS):
        if i < len(payload.get("sections") or []):
            if spec["id"] in excluded:
                payload["sections"][i]["rows"] = []
                payload["sections"][i]["omit"] = True
            else:
                payload["sections"][i]["omit"] = False
    for key, default in CHROME_FLAG_DEFAULTS.items():
        payload[key] = bool(flags.get(key, default))
    if flags.get("daily") is not False:
        payload["daily_balances"] = derive_daily_balances(payload)
    if flags.get("service") is not False:
        payload["service_charge"] = derive_service_charge(payload)
    return payload


class PreviewIn(BaseModel):
    model: dict
    flags: dict = Field(default_factory=dict)

class ProposeIn(BaseModel):
    model: dict
    request_text: str
    flags: dict = Field(default_factory=dict)

class JsonIn(BaseModel):
    raw: str


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "index.html").read_text()

@app.get("/static-app.js")
def static_app_js():
    return FileResponse(HERE / "static-app.js", media_type="text/javascript")

@app.get("/vendor/pdfjs/{name}")
def vendor_pdfjs(name: str):
    p = HERE / "vendor" / "pdfjs" / name
    if not p.exists():
        raise HTTPException(404, "missing")
    ctype = "text/javascript" if p.suffix == ".js" else "application/octet-stream"
    return FileResponse(p, media_type=ctype)

@app.get("/api/fixture/{key}")
def fixture(key: str):
    data = load_fixture(key)
    flags = default_flags(data)
    return {"model": data, "flags": flags, "summary": summary_from(data)}

@app.get("/api/blank")
def blank():
    data = blank_model()
    flags = default_flags(data)
    flags.update({"rewards": False, "daily": False, "service": False, "savings": False})
    return {"model": data, "flags": flags, "summary": summary_from(data)}

@app.post("/api/validate")
def api_validate(body: PreviewIn):
    data = normalize(body.model)
    errs = validate_model(data)
    return {"ok": not errs, "errors": errs, "summary": summary_from(data)}

@app.post("/api/preview")
def api_preview(body: PreviewIn, request: Request):
    data = normalize(body.model)
    flags = body.flags or {}
    errs = validate_model(data)
    if errs:
        return Response(content=json.dumps({"ok": False, "errors": errs}), media_type="application/json", status_code=422)
    payload = compose_payload({**data, "_flags": flags})
    if flags.get("show_sort_line", True):
        data["sort_line"] = apply_sort_mask(data.get("sort_line"), fill_unresolved=True)
        payload["sort_line"] = data["sort_line"]
    preview_path, last_ok = _session_paths(request)
    staging = preview_path.with_name(f"preview-{uuid.uuid4().hex}.pdf")
    try:
        compose(payload, staging)
    except Exception as e:
        staging.unlink(missing_ok=True)
        raise HTTPException(400, f"Composer rejected the model: {e}")
    pdf_bytes = staging.read_bytes()
    staging.replace(preview_path)
    last_ok.write_bytes(pdf_bytes)
    pages = 0
    try:
        import pymupdf as fitz
        pages = fitz.open(stream=pdf_bytes, filetype="pdf").page_count
    except Exception:
        hits = re.findall(rb"/Count\s+(\d+)", pdf_bytes)
        pages = int(hits[0]) if hits else max(pdf_bytes.count(b"/Type /Page"), 1)
    return {"ok": True, "pages": pages, "bytes": len(pdf_bytes), "composer": "Composer POC v3", "generated_at": datetime.utcnow().strftime("%H:%M:%S UTC"), "summary": summary_from(payload), "sort_line": data.get("sort_line"), "model": {"sort_line": data.get("sort_line")}}

@app.get("/api/preview.pdf")
def preview_pdf(request: Request):
    _, last_ok = _session_paths(request)
    preview_path, _ = _session_paths(request)
    src = last_ok if last_ok.exists() else preview_path
    if not src.exists():
        raise HTTPException(404, "No preview generated yet")
    return Response(
        content=src.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="DEMO-statement.pdf"'},
    )

@app.post("/api/propose")
def api_propose(body: ProposeIn):
    text = (body.request_text or "").strip()
    if not text:
        raise HTTPException(400, "Enter a request.")
    model = normalize(body.model)
    flags = copy.deepcopy(body.flags or {})
    flags.setdefault("excluded", [])
    year = datetime.utcnow().year
    a, b = parse_period(model.get("period") or "")
    if a:
        year = a.year
    changes = []
    patch_model = {}
    patch_flags = {}
    tl = text.lower()
    thru = re.search(r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\w*\s*(?:through|to|–|-)\s*(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)", tl)
    yr = re.search(r"(20\d{2})", text)

    def mon_from(token: str) -> int:
        return {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}[token[:3]]

    if thru:
        import calendar
        y = int(yr.group(1)) if yr else year
        m1, m2 = mon_from(thru.group(1)), mon_from(thru.group(2))
        start = datetime(y, m1, 1)
        end = datetime(y, m2, calendar.monthrange(y, m2)[1])
        patch_model["period"] = format_period(start, end)
        changes.append({"field": "Period", "from": model.get("period") or "—", "to": patch_model["period"]})
    elif "last six months" in tl or "past six months" in tl:
        import calendar
        end = b or datetime.utcnow()
        sm, sy = end.month - 5, end.year
        while sm <= 0:
            sm += 12; sy -= 1
        start = datetime(sy, sm, 1)
        patch_model["period"] = format_period(start, end)
        changes.append({"field": "Period", "from": model.get("period") or "—", "to": patch_model["period"]})

    def exclude(sid, label):
        ex = list(flags.get("excluded") or [])
        if sid not in ex:
            ex.append(sid)
        patch_flags["excluded"] = ex
        changes.append({"field": "Sections", "from": label, "to": "Excluded"})

    def include_flag(key, label, on=True):
        patch_flags[key] = on
        changes.append({"field": label, "from": "Current", "to": "Included" if on else "Excluded"})

    if any(w in tl for w in ("exclude", "without", "omit", "drop")) and any(w in tl for w in ("debit", "atm", "card")):
        exclude("cards", "ATM & Debit Card")
    if "deposits only" in tl or "salary" in tl or "payroll" in tl:
        patch_flags["excluded"] = ["checks", "cards", "electronic", "fees"]
        changes.append({"field": "Sections", "from": "All checking detail", "to": "Deposits only"})
    if "exclude savings" in tl or "without savings" in tl:
        include_flag("savings", "Savings", False)
    elif "savings" in tl:
        include_flag("savings", "Savings", True)
    if "rewards" in tl and any(w in tl for w in ("exclude", "without", "omit")):
        include_flag("rewards", "Rewards", False)
    if "rewards" in tl and "include" in tl:
        include_flag("rewards", "Rewards", True)
    if re.search(r"\b(show|include|display|turn on)\b", tl) and "daily" in tl:
        include_flag("daily", "Daily Ending Balance", True)
    if re.search(r"\b(hide|exclude|omit|without|turn off)\b", tl) and "daily" in tl:
        include_flag("daily", "Daily Ending Balance", False)

    invented = bool(
        re.search(r"\$\s*[\d,]+", text)
        or re.search(r"balance (of|to)|opening balance|amount of", tl)
        or re.search(r"(make|set|change|update).{0,30}ending balance", tl)
        or re.search(r"\b(deposit|withdraw|wire|transaction)s?\b.{0,40}\$", tl)
        or re.search(r"adding money|add money|make the totals|totals balance", tl)
    )
    note = None
    classification = "configuration"
    if invented and changes:
        classification = "mixed"
        note = (
            "Configuration changes can be proposed. Financial amounts in the request were not applied. "
            "Enter authorized balances or transactions in the structured controls."
        )
    elif invented:
        classification = "financial"
        note = (
            "Financial data cannot be generated from a request. "
            "Enter an authorized balance or transaction through the structured data controls."
        )
    elif not changes:
        classification = "unsupported"
        note = "No supported configuration change was recognized. Natural language may adjust period and included sections only."
    return {
        "changes": changes,
        "patch_model": patch_model,
        "patch_flags": patch_flags,
        "note": (note or "").strip() or None,
        "refused_financial_invention": invented,
        "classification": classification,
    }

@app.post("/api/json/validate")
def json_validate(body: JsonIn):
    try:
        data = json.loads(body.raw)
    except json.JSONDecodeError as e:
        return {"ok": False, "errors": [f"JSON parse error: {e}"]}
    if not isinstance(data, dict):
        return {"ok": False, "errors": ["Document model must be a JSON object."]}
    if "model" in data and isinstance(data["model"], dict):
        data = data["model"]
    data = normalize(data)
    errs = validate_model(data)
    return {"ok": not errs, "errors": errs, "model": data}

@app.get("/health")
def health():
    return {"status": "ok", "composer": "POC-v3"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
    )
