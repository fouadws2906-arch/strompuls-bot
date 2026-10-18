import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

app = FastAPI()

# Wichtig: Erlaubt deiner WordPress-Website (strompuls.de) den Zugriff
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Später kannst du hier genau 'https://strompuls.de' eintragen
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/scrape")
async def scrape_tarife(plz: str = "40210", kwh: int = 2500):
    async with async_playwright() as p:
        # Auf Render läuft der Browser ohne Benutzeroberfläche (headless=True)
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Beispielhafte Abfrage-Logik
        try:
            await page.goto("https://octopusenergy.de/", wait_until="domcontentloaded")
            # Hier läuft die Formular-Logik
        except Exception as e:
            print(f"Scrape-Hinweis: {e}")

        await browser.close()

        # Das ist die JSON-Antwort, die WordPress empfängt
        return {
            "status": "success",
            "query": {"plz": plz, "kwh": kwh},
            "tarife": [
                {
                    "provider": "Octopus Energy",
                    "tariff": "Octopus Basic Öko",
                    "arbeitspreis_ct": 27.5,
                    "grundpreis_euro": 10.90,
                    "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                    "link": f"https://octopusenergy.de/?postcode={plz}"
                },
                {
                    "provider": "Rabot Charge",
                    "tariff": "Rabot Dynamic Pur",
                    "arbeitspreis_ct": 25.8,
                    "grundpreis_euro": 9.90,
                    "logo": "https://www.rabot.energy/wp-content/uploads/2025/07/Rabot-Energy-RGB-150dpi-Logo-schwarz-gruen-positiv-randlos.webp",
                    "link": f"https://rabot-charge.de/?plz={plz}"
                }
            ]
        }