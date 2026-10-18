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

# Inicializa el cliente con la API Key gratuita de Groq
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

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
            # 1. Cargar la página
            await page.goto("https://energiemarie.de/stromanbieter/octopus-energy", wait_until="domcontentloaded", timeout=30000)

            # 2. Aceptar Cookies
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), #didomi-notice-agree-button, button:has-text('Akzeptieren')").first
                if await cookie_btn.is_visible(timeout=2500):
                    await cookie_btn.click()
            except Exception:
                pass

            # 3. Llenar formulario
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

            # 4. Extraer el texto completo
            raw_text = await page.evaluate("() => document.body.innerText")

            # 5. Prompt para el modelo gratuito Llama 3
            prompt = f"""
            Extract all Octopus Energy electricity tariffs from the following text for ZIP code {plz} and {kwh} kWh/year.

            Rules:
            1. Find the total annual price in euros (gross, e.g. 676).
            2. Extract working price (arbeitspreis_ct) and base price (grundpreis_euro).
            
            Return ONLY a valid JSON object with this exact structure:
            {{
              "tarife": [
                {{
                  "tariff": "Select+ Secure 24 Strom",
                  "arbeitspreis_ct": 38.05,
                  "grundpreis_euro": 8.79,
                  "preis_jahr_euro": 676.0
                }}
              ]
            }}

            Text:
            {raw_text[:4000]}
            """

            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )

            result_json = json.loads(completion.choices[0].message.content)
            extracted_tarife = result_json.get("tarife", [])

            referenz_preis_jahr = (kwh * 0.38) + (12.50 * 12)

            for item in extracted_tarife:
                preis_jahr = float(item.get("preis_jahr_euro", 0))
                preis_monat = round(preis_jahr / 12, 2)
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
            print(f"Error scraping/IA: {e}")

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
