import asyncio
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def clean_float(val_str: str) -> float:
    if not val_str:
        return 0.0
    match = re.search(r"(\d+[,.]?\d*)", val_str)
    if match:
        return float(match.group(1).replace(",", "."))
    return 0.0

@app.get("/scrape")
async def scrape_tarife(plz: str = "50667", kwh: int = 1500):
    tarife_liste = []
    referenz_preis_jahr = (kwh * 0.38) + (12.50 * 12)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # 1. Energiemarie (Selectra) aufrufen
            await page.goto("https://energiemarie.de/stromanbieter/octopus-energy", wait_until="networkidle", timeout=30000)

            # 2. Cookies akzeptieren
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), #didomi-notice-agree-button, button:has-text('Akzeptieren')").first
                if await cookie_btn.is_visible(timeout=3000):
                    await cookie_btn.click()
            except Exception:
                pass

            # 3. PLZ eingeben
            plz_input = page.locator("input[placeholder*='PLZ'], input[name*='zip'], input[id*='plz']").first
            if await plz_input.is_visible(timeout=3000):
                await plz_input.click()
                await plz_input.fill("")
                await plz_input.type(str(plz), delay=50)

            # 4. kWh eingeben
            kwh_input = page.locator("input[placeholder*='kWh'], input[name*='consumption'], input[id*='kwh']").first
            if await kwh_input.is_visible(timeout=3000):
                await kwh_input.click()
                await kwh_input.fill("")
                await kwh_input.type(str(kwh), delay=50)

            # 5. Formular absenden
            submit_btn = page.locator("button:has-text('Tarife anzeigen'), button:has-text('Berechnen')").first
            if await submit_btn.is_visible(timeout=3000):
                await submit_btn.click()

            # Warten bis die Ergebnisse geladen sind
            try:
                await page.wait_for_selector("text=Arbeitspreis", timeout=10000)
            except Exception:
                await page.wait_for_timeout(4000)

            # 6. Tarifkarten scannen
            all_divs = await page.locator("div").all()

            for div in all_divs:
                try:
                    card_text = await div.inner_text()

                    if "Arbeitspreis" in card_text and "Grundpreis" in card_text and len(card_text) < 900:
                        
                        # Tarif-Name auslesen
                        title = "Octopus Energy Tarif"
                        lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                        for line in lines:
                            if any(k in line.lower() for k in ["secure", "optimus", "select", "basic", "relax", "flux"]):
                                title = line
                                break

                        # Duplikate vermeiden
                        if any(t["tariff"] == title for t in tarife_liste):
                            continue

                        # Arbeitspreis (ct/kWh) & Grundpreis (€/Monat) für Details
                        ap_match = re.search(r"Arbeitspreis\s*(\d+[,.]\d+)", card_text)
                        arbeitspreis = clean_float(ap_match.group(1)) if ap_match else 0.0

                        gp_match = re.search(r"Grundpreis\s*(\d+[,.]\d+)", card_text)
                        grundpreis = clean_float(gp_match.group(1)) if gp_match else 0.0

                        # HAUPT-LOGIK: Direkt die große Zahl vor €/Jahr greifen (z. B. "684 €/Jahr")
                        # Wir suchen nach Zahlen > 200, um Bonuszahlungen auszuschließen
                        jahr_matches = re.findall(r"(\d{3,4})\s*€\s*/?\s*Jahr", card_text)
                        valid_prices = [clean_float(m) for m in jahr_matches if clean_float(m) > 200]

                        if valid_prices:
                            preis_jahr = valid_prices[0]  # Z. B. 684.00 €
                        else:
                            # Fallback falls nicht direkt gefunden
                            preis_jahr = round((kwh * (arbeitspreis / 100)) + (grundpreis * 12), 2)

                        # Monatlicher Preis = Exakt Jahrespreis / 12 (z. B. 684 / 12 = 57.00 €)
                        preis_monat = round(preis_jahr / 12, 2)
                        ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

                        if preis_jahr > 0:
                            tarife_liste.append({
                                "provider": "Octopus Energy",
                                "tariff": title,
                                "arbeitspreis_ct": arbeitspreis,
                                "grundpreis_euro": grundpreis,
                                "preis_monat_euro": preis_monat,
                                "preis_jahr_euro": preis_jahr,
                                "ersparnis_jahr_euro": ersparnis,
                                "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                                "link": f"https://octopusenergy.de/signup/1-start?postcode={plz}&kwh={kwh}"
                            })
                except Exception:
                    continue

        except Exception as e:
            print(f"Scraper Error: {e}")

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
