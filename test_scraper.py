import asyncio
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
async def scrape_tarife(plz: str = "40210", kwh: int = 2500):
    octopus_link = f"https://octopusenergy.de/?postcode={plz}"
    
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
            # 1. Startseite aufrufen
            await page.goto("https://octopusenergy.de/", wait_until="networkidle", timeout=30000)

            # Cookie-Banner akzeptieren (falls vorhanden)
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), button:has-text('Akzeptieren'), #onetrust-accept-btn-handler")
                if await cookie_btn.is_visible(timeout=3000):
                    await cookie_btn.click()
            except Exception:
                pass

            # 2. PLZ eintragen
            plz_input = page.locator("input[placeholder*='PLZ'], input[name*='postcode'], input[id*='postcode']").first
            await plz_input.fill(str(plz))

            # 3. Jahresverbrauch "Wenig" auswählen
            wenig_btn = page.locator("button:has-text('Wenig'), div:has-text('Wenig')").first
            if await wenig_btn.is_visible(timeout=2000):
                await wenig_btn.click()

            # 4. kWh-Feld mit dem Wert aus dem Formular befüllen
            kwh_input = page.locator("input[placeholder*='kWh'], input[name*='kwh'], input[id*='kwh']").first
            if await kwh_input.is_visible(timeout=2000):
                await kwh_input.fill("")
                await kwh_input.fill(str(kwh))

            # 5. Klick auf "Tarif finden"
            tarif_btn = page.locator("button:has-text('Tarif finden')").first
            await tarif_btn.click()

            # Warten, bis die Ergebnisseite geladen ist & URL abfangen
            await page.wait_for_url("**/signup/**", timeout=15000)
            octopus_link = page.url

        except Exception as e:
            print(f"Octopus Scrape Hinweis: {e}")
            # Fallback-URL mit Parametern verwenden
            octopus_link = f"https://octopusenergy.de/signup/2-tariff-selection?energyType=electricity&postcode={plz}&kwh={kwh}"

        finally:
            await browser.close()

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
                "link": octopus_link
            },
            {
                "provider": "Rabot Charge",
                "tariff": "Rabot Dynamic Pur",
                "arbeitspreis_ct": 25.8,
                "grundpreis_euro": 9.90,
                "logo": "https://www.rabot.energy/wp-content/uploads/2025/07/Rabot-Energy-RGB-150dpi-Logo-schwarz-gruen-positiv-randlos.webp",
                "link": f"https://funnel.rabot.energy/tariff-details?plz={plz}&consumption={kwh}&kwh={kwh}"
            }
        ]
    }
