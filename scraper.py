#!/usr/bin/env python3
"""Octopus-Tarif-Scraper für strompuls.de

Ablauf wie ein Besucher auf octopusenergy.de:
  PLZ eingeben -> "Wenig" klicken -> kWh/Jahr eintragen -> "Tarif finden"
  -> Tarifkarten (relax12, relax24, ...) auslesen -> tarife.json

Aufruf:  python scraper.py --plz-file plz.csv --max 300   (alle PLZ, 300 pro Lauf, rollierend)
         python scraper.py --plz-file plz.txt
         python scraper.py --plz 44139 --kwh 2500
"""
import argparse, csv, hashlib, json, os, random, re, sys, time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

START_URL = "https://octopusenergy.de/"
OUT = Path("tarife.json")
STATE = Path("state.json")
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


def pick_first_option(page):
    try:
        page.get_by_role("option").filter(visible=True).first.click(timeout=2500)
        return True
    except Exception:
        return False


def fill_address(page):
    """PLZ mit mehreren Tarifgebieten: Octopus fragt Ort, Straße und Hausnummer ab.
    Wir tippen einen Vokal, nehmen den ersten Vorschlag und Hausnummer 1."""
    try:   # Ort: nur wenn leer
        ort = page.get_by_label(re.compile(r"^Ort$", re.I)).filter(visible=True).first
        if not (ort.input_value(timeout=1500) or "").strip():
            ort.click()
            ort.press_sequentially("a", delay=80)
            page.wait_for_timeout(900)
            pick_first_option(page)
    except Exception:
        pass
    for vowel in ("a", "e", "i", "o", "u"):
        try:
            st = page.get_by_label(re.compile(r"Stra(ß|ss)e", re.I)).filter(visible=True).first
            st.click(timeout=3000)
            st.press("Control+A")
            st.press_sequentially(vowel, delay=80)
            page.wait_for_timeout(1000)
            if pick_first_option(page):
                break
        except Exception:
            continue
    fill_field(page, r"Hausnummer", "1")
    page.keyboard.press("Tab")
    page.wait_for_timeout(1200)
    for label in ("Tarife anzeigen", "Tarife ansehen", "Tarife finden", "Weiter"):
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).filter(visible=True).first.click(timeout=1500)
            break
        except Exception:
            pass
    return True


def sammle_tarife(page):
    tarife = []
    buttons = page.get_by_text(re.compile(r"^\s*Tarif wählen\s*$"))
    for i in range(buttons.count()):
        t = buttons.nth(i).evaluate(CARD_JS)
        card = parse_card(t) if t else None
        if card:
            tarife.append(card)
    return tarife


def ergebnis_da(page, sekunden):
    try:
        page.wait_for_selector("text=Arbeitspreis", timeout=sekunden * 1000)
        return True
    except Exception:
        return False


def adresse_ausfuellen(page, buchstabe, idx):
    """PLZ mit mehreren Tarifgebieten: Straße per Buchstabe wählen + Hausnummer 1."""
    try:    # Ort leer? Dann ersten Vorschlag nehmen
        ort = page.get_by_label(re.compile(r"^Ort", re.I)).filter(visible=True).first
        if not ort.input_value():
            ort.click(timeout=2000)
            page.get_by_role("option").filter(visible=True).first.click(timeout=3000)
    except Exception:
        pass
    strasse = page.get_by_label(re.compile(r"Stra(ß|ss)e", re.I)).filter(visible=True).first
    strasse.click(timeout=4000)
    strasse.press("Control+A")
    strasse.press_sequentially(buchstabe, delay=100)
    page.wait_for_timeout(1500)
    opts = page.get_by_role("option").filter(visible=True)
    n = opts.count()
    if n == 0:
        return False
    opts.nth(min(idx, n - 1)).click(timeout=3000)
    fill_field(page, r"Hausnummer", "1")
    page.keyboard.press("Tab")
    page.wait_for_timeout(800)
    for label in ("Tarife anzeigen", "Angebote anzeigen", "Tarif finden", "Weiter"):
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).filter(visible=True).first.click(timeout=1500)
            break
        except Exception:
            pass
    return True


def scrape_plz(browser, plz, kwh, buchstabe="a", idx=0, debug=True):
    """Gibt (tarife, adresse_noetig) zurück."""
    ctx = browser.new_context(locale="de-DE", viewport={"width": 1366, "height": 900},
                              user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                          "Chrome/124.0 Safari/537.36"))
    page = ctx.new_page()
    tarife, adresse = [], False
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

        if not ergebnis_da(page, 12):
            hat_strasse = page.get_by_label(re.compile(r"Stra(ß|ss)e", re.I)).filter(visible=True).count() > 0
            if hat_strasse:
                adresse = True
                if adresse_ausfuellen(page, buchstabe, idx):
                    ergebnis_da(page, 30)
            else:
                ergebnis_da(page, 20)
        page.wait_for_timeout(1000)
        tarife = sammle_tarife(page)
    except Exception as e:
        print(f"[{plz}] Fehler: {e}", file=sys.stderr)
    finally:
        if debug:
            try:
                DEBUG.mkdir(exist_ok=True)
                page.screenshot(path=str(DEBUG / f"{plz}.png"), full_page=True)
                (DEBUG / f"{plz}.txt").write_text(page.inner_text("body"))
            except Exception:
                pass
        ctx.close()
    return tarife, adresse


def read_plz(path):
    """PLZ aus .txt (eine pro Zeile) oder .csv (Spalte 'plz') lesen."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with p.open(encoding="utf-8-sig", newline="") as f:
            sample = f.read(2048)
            f.seek(0)
            delim = ";" if sample.count(";") > sample.count(",") else ","
            rows = csv.DictReader(f, delimiter=delim)
            cols = {(k or "").lower().strip(): k for k in (rows.fieldnames or [])}
            key = cols.get("plz") or cols.get("postleitzahl")
            vals = [(r.get(key) or "").strip().zfill(5) for r in rows] if key else []
    else:
        vals = [l.strip() for l in p.read_text().splitlines()]
    return sorted({v for v in vals if re.fullmatch(r"\d{5}", v)})


def gruppe_id(tarife):
    return hashlib.md5(json.dumps(tarife, sort_keys=True).encode()).hexdigest()[:8]


def save(data, state):
    used = set()
    for v in data["plz"].values():
        used.update(v if isinstance(v, list) else [v])
    data["gruppen"] = {k: v for k, v in data["gruppen"].items() if k in used}
    data["stand"] = date.today().strftime("%d.%m.%Y")
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    STATE.write_text(json.dumps(state))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plz", default="")
    ap.add_argument("--plz-file", default="")
    ap.add_argument("--kwh", type=int, default=2500)
    ap.add_argument("--max", type=int, default=0, help="PLZ pro Lauf (0 = alle); rollierend")
    a = ap.parse_args()

    plzs = [p.strip() for p in a.plz.split(",") if p.strip()]
    if a.plz_file:
        plzs += read_plz(a.plz_file)
    plzs = sorted(set(plzs))
    if not plzs:
        sys.exit("Keine PLZ angegeben.")

    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    data.setdefault("gruppen", {})
    data.setdefault("plz", {})
    state = json.loads(STATE.read_text()) if STATE.exists() else {"offset": 0}

    start = state.get("offset", 0) % len(plzs)
    if a.max and a.max < len(plzs):
        batch = (plzs[start:] + plzs[:start])[:a.max]
        state["offset"] = (start + a.max) % len(plzs)
    else:
        batch, state["offset"] = plzs, 0
    print(f"{len(plzs)} PLZ insgesamt, dieser Lauf: {len(batch)} (ab Position {start})")

    ok = fails = streak = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for i, plz in enumerate(batch, 1):
            tarife, adr = scrape_plz(browser, plz, a.kwh)
            gruppen = {gruppe_id(tarife): tarife} if tarife else {}
            if tarife and adr:    # mehrere Tarifgebiete: zwei weitere Straßen prüfen
                for buchstabe, idx in (("e", 1), ("i", 2)):
                    time.sleep(random.uniform(2, 4))
                    t2, _ = scrape_plz(browser, plz, a.kwh, buchstabe, idx, debug=False)
                    if t2:
                        gruppen[gruppe_id(t2)] = t2
            print(f"[{plz}] {len(gruppen)} Tarifgebiet(e)" + (" (mit Adresse)" if adr else "") + ": " +
                  ", ".join(f"{t['tarif']} {t['ap']} ct / {t['gp']} EUR" for t in tarife))
            if gruppen:                      # bei Fehlschlag alte Daten behalten
                data["gruppen"].update(gruppen)
                ids = list(gruppen)
                data["plz"][plz] = ids[0] if len(ids) == 1 else ids
                ok += 1
                streak = 0
            else:
                fails += 1
                streak += 1
                if streak >= 8 and ok == 0:  # Seite hat sich wohl geaendert: nicht weiter hammern
                    print("8 Fehlschlaege in Folge, Abbruch.", file=sys.stderr)
                    break
            if i % 25 == 0:
                save(data, state)
            time.sleep(random.uniform(2, 4))
        browser.close()

    save(data, state)
    print(f"{ok} PLZ aktualisiert, {fails} ohne Ergebnis, {len(data['plz'])} PLZ insgesamt in tarife.json")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
