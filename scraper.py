#!/usr/bin/env python3
"""Octopus-Tarif-Scraper für strompuls.de

Ablauf wie ein Besucher auf octopusenergy.de:
  PLZ eingeben -> "Wenig" klicken -> kWh/Jahr eintragen -> "Tarif finden"
  -> Tarifkarten (relax12, relax24, ...) auslesen -> tarife.json

Aufruf:  python scraper.py --plz-file plz.txt
         python scraper.py --plz 44139 --kwh 2500
"""
import argparse, json, os, random, re, sys, time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

START_URL = "https://octopusenergy.de/"
OUT = Path("tarife.json")
DEBUG = Path("debug")
LINK = os.environ.get("AFFILIATE_LINK") or START_URL

# Liefert den Text der Tarifkarte, in der ein "Tarif wählen"-Button steckt.
CARD_JS = """el => { let n = el;
  while (n.parentElement) {
    n = n.parentElement;
    const t = n.innerText || "";
    if (/Arbeitspreis/.test(t) && /Tarifdetails/.test(t)) {
      return (t.match(/Arbeitspreis/g) || []).length === 1 ? t : "";
    }
  }
  return ""; }"""


def de_num(s):
    s = s.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def parse_card(t):
    """Eine Tarifkarte (Text) in ein Tarif-Dict umwandeln."""
    ap = re.search(r"Arbeitspreis:?\s*([\d.,]+)\s*ct", t, re.I)
    gp = re.search(r"Grundpreis:?\s*([\d.,]+)\s*€", t, re.I)
    if not (ap and gp):
        return None
    lz = re.search(r"(\d+)\s*Monate\s*Mindestvertrag", t, re.I)
    pg = re.search(r"(\d+)\s*Monate\s*Preisgarantie", t, re.I)
    nm = re.search(r"relax\s*\d+", t, re.I)
    if nm:
        name = "Octopus " + nm.group(0).replace(" ", "")
    elif lz:
        name = f"Octopus {lz.group(1)} Monate"
    else:
        name = "Octopus Tarif"
    return {"anbieter": "Octopus Energy", "tarif": name,
            "ap": round(de_num(ap.group(1)), 2), "gp": round(de_num(gp.group(1)), 2),
            "bonus": 0,
            "laufzeit": f"{lz.group(1)} Monate" if lz else "",
            "garantie": f"{pg.group(1)} Monate" if pg else "",
            "oeko": True, "plz": [], "link": LINK}


def accept_cookies(page):
    for label in ("Alle akzeptieren", "Alles akzeptieren", "Alle Cookies akzeptieren", "Akzeptieren", "Zustimmen"):
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).filter(visible=True).first.click(timeout=2000)
            return
        except Exception:
            pass


def fill_field(page, pattern, value):
    """Sichtbares Feld finden (Seite hat Desktop- und Mobil-Formular), leeren, tippen."""
    rx = re.compile(pattern, re.I)
    makers = (lambda: page.get_by_placeholder(rx), lambda: page.get_by_label(rx),
              lambda: page.get_by_role("textbox", name=rx), lambda: page.get_by_role("spinbutton", name=rx))
    for make in makers:
        try:
            loc = make().filter(visible=True).first
            loc.click(timeout=3000)
            loc.press("Control+A")
            loc.press_sequentially(str(value), delay=60)
            return True
        except Exception:
            continue
    return False


def scrape_plz(browser, plz, kwh):
    ctx = browser.new_context(locale="de-DE", viewport={"width": 1366, "height": 900},
                              user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                          "Chrome/124.0 Safari/537.36"))
    page = ctx.new_page()
    tarife = []
    try:
        page.goto(START_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        accept_cookies(page)

        if not fill_field(page, r"Deine PLZ|PLZ", plz):
            print(f"[{plz}] PLZ-Feld nicht gefunden", file=sys.stderr)
        page.wait_for_timeout(1200)
        try:   # falls eine Ortsauswahl erscheint
            page.get_by_role("option").filter(visible=True).first.click(timeout=1500)
        except Exception:
            pass

        try:
            page.get_by_text("Wenig", exact=True).filter(visible=True).first.click(timeout=3000)
        except Exception:
            print(f"[{plz}] 'Wenig' nicht gefunden", file=sys.stderr)
        if not fill_field(page, r"kWh", kwh):
            print(f"[{plz}] kWh-Feld nicht gefunden", file=sys.stderr)

        page.get_by_role("button", name=re.compile(r"Tarif finden", re.I)).filter(visible=True).first.click(timeout=5000)
        page.wait_for_selector("text=Arbeitspreis", timeout=40000)
        page.wait_for_timeout(1500)

        buttons = page.get_by_text(re.compile(r"^\s*Tarif wählen\s*$"))
        for i in range(buttons.count()):
            t = buttons.nth(i).evaluate(CARD_JS)
            card = parse_card(t) if t else None
            if card:
                tarife.append(card)
    except Exception as e:
        print(f"[{plz}] Fehler: {e}", file=sys.stderr)
    finally:
        try:
            DEBUG.mkdir(exist_ok=True)
            page.screenshot(path=str(DEBUG / f"{plz}.png"), full_page=True)
            (DEBUG / f"{plz}.txt").write_text(page.inner_text("body"))
        except Exception:
            pass
        ctx.close()
    return tarife


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plz", default="")
    ap.add_argument("--plz-file", default="")
    ap.add_argument("--kwh", type=int, default=2500)
    a = ap.parse_args()

    plzs = [p.strip() for p in a.plz.split(",") if p.strip()]
    if a.plz_file:
        plzs += [l.strip() for l in Path(a.plz_file).read_text().splitlines() if l.strip().isdigit()]
    plzs = sorted(set(plzs))
    if not plzs:
        sys.exit("Keine PLZ angegeben.")

    data = json.loads(OUT.read_text()) if OUT.exists() else {"tarife": {}}
    ok = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for plz in plzs:
            tarife = scrape_plz(browser, plz, a.kwh)
            print(f"[{plz}] {len(tarife)} Tarife: " + ", ".join(f"{t['tarif']} {t['ap']} ct / {t['gp']} €" for t in tarife))
            if tarife:                       # bei Fehlschlag alte Daten behalten
                data["tarife"][plz] = tarife
                ok += 1
            time.sleep(random.uniform(3, 6))
        browser.close()

    data["stand"] = date.today().strftime("%d.%m.%Y")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"{ok}/{len(plzs)} PLZ aktualisiert")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
