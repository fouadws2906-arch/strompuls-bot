import os
import json
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

@app.get("/scrape")
async def scrape_octopus_real(plz: str = "44339", kwh: float = 1500.0):
    tarife_liste = []

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
            # 1. Seite aufrufen
            await page.goto(f"https://octopusenergy.de/signup/1-start?postcode={plz}", wait_until="networkidle", timeout=30000)

            # 2. Cookies akzeptieren
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), #onetrust-accept-btn-handler").first
                if await cookie_btn.is_visible(timeout=3000):
                    await cookie_btn.click()
            except Exception:
                pass

            # 3. kWh eingeben & berechnen
            try:
                kwh_input = page.locator("input[name*='consumption'], input[id*='kwh'], input[type='number']").first
                if await kwh_input.is_visible(timeout=3000):
                    await kwh_input.fill("")
                    await kwh_input.type(str(int(kwh)), delay=50)

                submit_btn = page.locator("button[type='submit'], button:has-text('Weiter'), button:has-text('Tarife anzeigen')").first
                if await submit_btn.is_visible(timeout=3000):
                    await submit_btn.click()
                    await page.wait_for_timeout(4000)
            except Exception:
                pass

            # 4. Echte Preise aus den gerenderten Kacheln auslesen
            cards = await page.locator("div[class*='TariffCard'], div[class*='card'], article").all()
            referenz_preis_jahr = (kwh * 0.38) + (12.50 * 12)

            for card in cards:
                text = await card.inner_text()
                if "ct/kWh" in text or "€" in text:
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    name = lines[0] if lines else "Octopus Tarif"

                    ap_match = re.search(r'(\d+[\.,]\d+)\s*ct', text)
                    gp_match = re.search(r'(\d+[\.,]\d+)\s*€\s*\/\s*Monat', text)

                    if ap_match:
                        ap = float(ap_match.group(1).replace(",", "."))
                        gp = float(gp_match.group(1).replace(",", ".")) if gp_match else 11.50
                        
                        preis_jahr = round((kwh * (ap / 100)) + (gp * 12), 2)
                        preis_monat = round(preis_jahr / 12, 2)
                        ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

                        tarife_liste.append({
                            "provider": "Octopus Energy",
                            "tariff": name,
                            "arbeitspreis_ct": ap,
                            "grundpreis_euro": gp,
                            "preis_monat_euro": preis_monat,
                            "preis_jahr_euro": preis_jahr,
                            "ersparnis_jahr_euro": ersparnis,
                            "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                            "link": f"https://octopusenergy.de/signup/1-start?postcode={plz}&kwh={kwh}"
                        })

        except Exception as e:
            print(f"Scrape Fehler: {e}")

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
