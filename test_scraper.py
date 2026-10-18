import asyncio
import json
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
import openai  # oder ein anderer KI-Anbieter

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = openai.OpenAI(api_key="DEIN_OPENAI_API_KEY")

@app.get("/scrape")
async def scrape_tarife(plz: str = "10115", kwh: int = 1500):
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
            await page.goto("https://energiemarie.de/stromanbieter/octopus-energy", wait_until="domcontentloaded", timeout=30000)

            # Cookie Banner
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), #didomi-notice-agree-button, button:has-text('Akzeptieren')").first
                if await cookie_btn.is_visible(timeout=2500):
                    await cookie_btn.click()
            except Exception:
                pass

            # PLZ + kWh Formular
            plz_input = page.locator("input[placeholder*='PLZ'], input[name*='zip'], input[id*='plz']").first
            if await plz_input.is_visible(timeout=3000):
                await plz_input.fill("")
                await plz_input.type(str(plz), delay=40)

            kwh_input = page.locator("input[placeholder*='kWh'], input[name*='consumption'], input[id*='kwh']").first
            if await kwh_input.is_visible(timeout=3000):
                await kwh_input.fill("")
                await kwh_input.type(str(kwh), delay=40)

            submit_btn = page.locator("button:has-text('Tarife anzeigen'), button:has-text('Berechnen')").first
            if await submit_btn.is_visible(timeout=3000):
                await submit_btn.click()

            await page.wait_for_timeout(4000)

            # Extrahiere den reinen Text des relevanten Bereichs
            page_text = await page.evaluate("() => document.body.innerText")

            # KI-PROMPT: Extrahieren der exakten Tarifstruktur als JSON
            prompt = f"""
            Du bist ein Daten-Parser. Extrahiere alle Octopus Energy Stromtarife aus folgendem Website-Text für PLZ {plz} und {kwh} kWh.
            
            Wichtig:
            - Nimm den tatsächlichen Jahrespreis (brutto, inkl. Boni/Steuern) der großen Anzeige (z. B. 676 €/Jahr).
            - Berechne oder entnimm den Monatspreis (z. B. 56.33 €/Monat).
            
            Gib ausschließlich ein valides JSON-Array im folgenden Format zurück:
            [
              {{
                "tariff": "Select+ Secure 24 Strom",
                "arbeitspreis_ct": 38.05,
                "grundpreis_euro": 8.79,
                "preis_jahr_euro": 676.0,
                "preis_monat_euro": 56.33,
                "bonus_euro": 119.0
              }}
            ]

            Website-Text:
            {page_text[:4000]}
            """

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )

            raw_json = response.choices[0].message.content
            parsed_data = json.loads(raw_json)

            # Falls KI ein Objekt mit Key "tarife" liefert, anpassen
            items = parsed_data if isinstance(parsed_data, list) else parsed_data.get("tarife", parsed_data.get("results", []))

            referenz_preis_jahr = (kwh * 0.38) + (12.50 * 12)

            for item in items:
                preis_jahr = float(item.get("preis_jahr_euro", 0))
                preis_monat = float(item.get("preis_monat_euro", round(preis_jahr / 12, 2)))
                ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

                tarife_liste.append({
                    "provider": "Octopus Energy",
                    "tariff": item.get("tariff", "Octopus Energy Tarif"),
                    "arbeitspreis_ct": float(item.get("arbeitspreis_ct", 0)),
                    "grundpreis_euro": float(item.get("grundpreis_euro", 0)),
                    "preis_monat_euro": preis_monat,
                    "preis_jahr_euro": preis_jahr,
                    "ersparnis_jahr_euro": ersparnis,
                    "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                    "link": f"https://octopusenergy.de/signup/1-start?postcode={plz}&kwh={kwh}"
                })

        except Exception as e:
            print(f"Fehler beim Scraping/KI: {e}")

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
