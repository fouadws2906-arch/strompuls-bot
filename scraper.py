#!/usr/bin/env python3
"""Octopus-Tarif-Scraper für strompuls.de

Öffnet den Octopus-Anmeldeprozess wie ein Besucher, gibt PLZ + Verbrauch ein,
fängt die JSON-Antworten ab und schreibt die gefundenen Tarife nach tarife.json.
Alle abgefangenen Antworten landen zusätzlich in debug/ (zum Nachjustieren).

Aufruf:  python scraper.py --plz-file plz.txt
         python scraper.py --plz 44139,44135 --kwh 2500
"""
import argparse, json, os, random, re, sys, time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

START_URL = "https://octopusenergy.de/signup/1-start?energyType=electricity"
OUT = Path("tarife.json")
DEBUG = Path("debug")
LINK = os.environ.get("AFFILIATE_LINK") or "https://octopusenergy.de/signup/1-start"

# Nach dem ersten Debug-Lauf hier die echten Feldnamen von Octopus ergänzen.
KEYS_AP = ("arbeitspreis", "unitrate", "unit_rate", "energyprice", "workingprice", "pricekwh", "priceperkwh")
KEYS_GP = ("grundpreis", "standingcharge", "standing_charge", "baseprice", "basicfee", "monthlyfee")
KEYS_NAME = ("displayname", "tariffname", "productname", "name", "title")


def num(v):
    """Zahl aus int/float/'27,9 ct'/{'gross':..} lesen, sonst None."""
    if isinstance(v, dict):
        for k in ("gross", "brutto", "amount", "value", "price"):
            if k in v:
                return num(v[k])
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:[.,]\d+)?", v)
        return float(m.group(0).replace(",", ".")) if m else None
    return None


def pick(d, keys):
    for k, v in d.items():
        kl = k.lower()
        if any(x in kl for x in keys):
            n = num(v)
            if n is not None:
                return n
    return None


def name_of(d):
    for want in KEYS_NAME:
        for k, v in d.items():
            if k.lower() == want and isinstance(v, str) and v.strip():
                return v.strip()
    return "Octopus Tarif"


def walk(node, found):
    if isinstance(node, dict):
        ap, gp = pick(node, KEYS_AP), pick(node, KEYS_GP)
        if ap is not None and gp is not None:
            if ap < 2:          # €/kWh -> ct/kWh
                ap *= 100
            found.append({"anbieter": "Octopus Energy", "tarif": name_of(node),
                          "ap": round(ap, 2), "gp": round(gp, 2), "bonus": 0,
                          "laufzeit": "", "garantie": "", "oeko": True,
                          "plz": [], "link": LINK})
        for v in node.values():
            walk(v, found)
    elif isinstance(node, list):
        for v in node:
            walk(v, found)


def extract(responses):
    found = []
    for r in responses:
        walk(r["body"], found)
    seen, out = set(), []
    for t in found:
        key = (t["tarif"], t["ap"], t["gp"])
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def accept_cookies(page):
    for label in ("Alle akzeptieren", "Alles akzeptieren", "Alle Cookies akzeptieren", "Akzeptieren"):
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=2000)
            return
        except Exception:
            pass


def fill_field(page, patterns, value):
    for p in patterns:
        rx = re.compile(p, re.I)
        for getter in (page.get_by_label, page.get_by_placeholder):
            try:
                getter(rx).first.fill(str(value), timeout=3000)
                return True
            except Exception:
                continue
    return False


def click_next(page):
    for label in ("Tarif finden", "Angebot", "Weiter", "Los geht"):
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=3000)
            return True
        except Exception:
            pass
    return False


def scrape_plz(browser, plz, kwh):
    ctx = browser.new_context(locale="de-DE", user_agent=(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 strompuls-bot (partner)"))
    page = ctx.new_page()
    responses = []

    def on_resp(r):
        try:
            if "json" in (r.headers.get("content-type") or ""):
                responses.append({"url": r.url, "status": r.status, "body": r.json()})
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        page.goto(START_URL, wait_until="networkidle", timeout=45000)
        accept_cookies(page)
        if not fill_field(page, ("PLZ", "Postleitzahl"), plz):
            print(f"[{plz}] PLZ-Feld nicht gefunden", file=sys.stderr)
        fill_field(page, ("kWh", "Verbrauch"), kwh)
        click_next(page)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        DEBUG.mkdir(exist_ok=True)
        (DEBUG / f"{plz}.json").write_text(json.dumps(responses, ensure_ascii=False, indent=1))
        page.screenshot(path=str(DEBUG / f"{plz}.png"), full_page=True)
    except Exception as e:
        print(f"[{plz}] Fehler: {e}", file=sys.stderr)
    finally:
        ctx.close()
    return extract(responses)


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
            print(f"[{plz}] {len(tarife)} Tarife")
            if tarife:                       # bei Fehlschlag alte Daten behalten
                data["tarife"][plz] = tarife
                ok += 1
            time.sleep(random.uniform(3, 6))  # höflich bleiben
        browser.close()

    data["stand"] = date.today().strftime("%d.%m.%Y")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"{ok}/{len(plzs)} PLZ aktualisiert")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
