import os
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
from groq import Groq

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/scrape")
async def scrape_tarife(plz: str = "10115", kwh: int = 1500):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": "GROQ_API_KEY ist nicht in den Render-Umgebungsvariablen hinterlegt."
        }

    client = Groq(api_key=api_key)
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
            # 1. Direkt zur Octopus Energy Rechner-Seite navigieren
            await page.goto(f"https://octopusenergy.de/signup/1-start?postcode={plz}", wait_until="domcontentloaded", timeout=30000)

            # 2. Cookie Banner akzeptieren
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), button:has-text('Akzeptieren'), #onetrust-accept-btn-handler").first
                if await cookie_btn.is_visible(timeout=3000):
                    await cookie_btn.click()
            except Exception:
                pass

            # 3. Falls nach Strom/Gas gefragt wird oder Verbrauchsangaben eingegeben werden müssen
            try:
                # Verbrauchs-Eingabefeld suchen und ausfüllen
                kwh_input = page.locator("input[name*='consumption'], input[id*='kwh'], input[type='number']").first
                if await kwh_input.is_visible(timeout=3000):
                    await kwh_input.fill("")
                    await kwh_input.type(str(kwh), delay=40)
                    
                # Weiter / Berechnen Button klicken
                submit_btn = page.locator("button[type='submit'], button:has-text('Weiter'), button:has-text('Tarife anzeigen')").first
                if await submit_btn.is_visible(timeout=3000):
                    await submit_btn.click()
            except Exception:
                pass

            await page.wait_for_timeout(4000)

            # 4. Text-Inhalt der Rechner-Seite auslesen
            raw_text = await page.evaluate("() => document.body.innerText")

            # 5. Groq KI Prompt (Aktualisiertes Modell llama-3.3-70b-versatile)
            prompt = f"""
            Analysiere den folgenden Text von der Octopus Energy Webseite für die PLZ {plz} und einen Jahresverbrauch von {kwh} kWh.
            Extrahiere alle angebotenen Stromtarife mit ihren Preisen.

            Gib das Ergebnis AUSSCHLIESSLICH im folgenden JSON-Format zurück:
            {{
              "tarife": [
                {{
                  "tariff": "Octopus Classic",
                  "arbeitspreis_ct": 28.50,
                  "grundpreis_euro": 10.50,
                  "preis_jahr_euro": 553.50
                }}
              ]
            }}

            Webseiten-Text:
            {raw_text[:6000]}
            """

            # Aktuelles Groq-Modell aufrufen
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )

            result_json = json.loads(completion.choices[0].message.content)
            extracted_tarife = result_json.get("tarife", [])

            referenz_preis_jahr = (kwh * 0.38) + (12.50 * 12)

            for item in extracted_tarife:
                preis_jahr = float(item.get("preis_jahr_euro", 0))
                preis_monat = round(preis_jahr / 12, 2) if preis_jahr > 0 else 0
                ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

                if preis_jahr > 0:
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
            print(f"Scraper Error: {e}")

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
