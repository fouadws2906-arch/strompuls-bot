"""strompuls Live-Server (100% Live)"""
import json
import os
import queue
import re
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# El directorio de datos, mapeado al disco duro de Fly.io
DATA_DIR = Path(os.environ.get("DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TAGE = int(os.environ.get("CACHE_TAGE", "7"))
SCRAPE_KWH = int(os.environ.get("SCRAPE_KWH", "2500"))
ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "https://strompuls.de,https://www.strompuls.de").split(",") if o.strip()]
MAX_QUEUE = int(os.environ.get("MAX_QUEUE", "100"))
LIMIT_PRO_STUNDE = int(os.environ.get("LIMIT_PRO_STUNDE", "10"))
FEHLER_SPERRE = 3600

_db_lock = threading.Lock()
_q_lock = threading.Lock()
_db = sqlite3.connect(DATA_DIR / "cache.db", check_same_thread=False)
_db.execute("CREATE TABLE IF NOT EXISTS plz (plz TEXT PRIMARY KEY, ts REAL, data TEXT)")
_db.commit()

jobs = queue.Queue()
pending = set()
failed = {}
hits = {}

BEKANNT = None
if Path("plz.txt").exists():
    BEKANNT = {l.strip() for l in Path("plz.txt").read_text().splitlines() if re.fullmatch(r"\d{5}", l.strip())}


def cache_get(plz):
    with _db_lock:
        row = _db.execute("SELECT ts, data FROM plz WHERE plz=?", (plz,)).fetchone()
    if row and time.time() - row[0] < CACHE_TAGE * 86400:
        return json.loads(row[1])
    return None


def cache_put(plz, gruppen):
    data = {"gruppen": gruppen, "stand": date.today().strftime("%d.%m.%Y")}
    with _db_lock:
        _db.execute("REPLACE INTO plz VALUES (?,?,?)", (plz, time.time(), json.dumps(data, ensure_ascii=False)))
        _db.commit()
    return data


def abfrage(plz, ip):
    if not re.fullmatch(r"\d{5}", plz or ""):
        return 400, {"status": "ungueltig"}
    if BEKANNT is not None and plz not in BEKANNT:
        return 200, {"status": "unbekannt"}
    data = cache_get(plz)
    if data:
        return 200, {"status": "ready", "plz": plz, **data}
    now = time.time()
    with _q_lock:
        if plz in pending:
            return 200, {"status": "pending", "warteschlange": jobs.qsize()}
        if now - failed.get(plz, 0) < FEHLER_SPERRE:
            return 200, {"status": "unavailable"}
        h = [t for t in hits.get(ip, []) if now - t < 3600]
        if len(h) >= LIMIT_PRO_STUNDE:
            hits[ip] = h
            return 429, {"status": "limit"}
        if jobs.qsize() >= MAX_QUEUE:
            return 200, {"status": "busy"}
        h.append(now)
        hits[ip] = h
        pending.add(plz)
        jobs.put(plz)
        return 200, {"status": "pending", "warteschlange": jobs.qsize()}


def worker():
    from playwright.sync_api import sync_playwright
    import scraper

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        while True:
            plz = jobs.get()
            try:
                tarife = scraper.scrape_plz(browser, plz, SCRAPE_KWH)
                if tarife:
                    cache_put(plz, tarife)
                else:
                    failed[plz] = time.time()
            except Exception as e:
                print(f"[{plz}] Fehler im Worker: {e}", flush=True)
                failed[plz] = time.time()
                try:
                    browser.close()
                except Exception:
                    pass
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                )
            finally:
                with _q_lock:
                    pending.discard(plz)
            time.sleep(2)


app = FastAPI(title="strompuls live")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ORIGINS == ["*"] else ORIGINS,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.on_event("startup")
def start_worker():
    threading.Thread(target=worker, daemon=True).start()


@app.get("/tarife")
def tarife(plz: str, request: Request):
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    code, body = abfrage(plz, ip)
    if code == 400:
        raise HTTPException(400, "PLZ ungueltig")
    return JSONResponse(body, status_code=code)


@app.get("/health")
def health():
    return {"ok": True, "warteschlange": jobs.qsize(), "wartend": len(pending)}
