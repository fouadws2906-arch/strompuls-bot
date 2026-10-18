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
    """ Convierte cadenas de texto numéricas en alemán ('44,35 €') a float """
    match = re.search(r"(\d+[,.]?\d*)", val_str)
    if match:
        return float(match.group(1).replace(",", "."))
    return 0.0

@app.get("/scrape")
async def scrape_tarife(plz: str = "10115", kwh: int = 1500):
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
            # Navegar a Energiemarie - Octopus Energy
            await page.goto("https://energiemarie.de/stromanbieter/octopus-energy", wait_until="domcontentloaded", timeout=25000)

            # Cookie Banner
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), #didomi-notice-agree-button, button:has-text('Akzeptieren')").first
                if await cookie_btn.is_visible(timeout=3000):
                    await cookie_btn.click()
            except Exception:
                pass

            # Rellenar PLZ
            plz_input = page.locator("input[name*='zip'], input[placeholder*='PLZ'], input[id*='plz']").first
            if await plz_input.is_visible(timeout=3000):
                await plz_input.fill(str(plz))

            # Rellenar kWh
            kwh_input = page.locator("input[name*='consumption'], input[placeholder*='kWh'], input[id*='kwh']").first
            if await kwh_input.is_visible(timeout=3000):
                await kwh_input.fill("")
                await kwh_input.fill(str(kwh))

            # Click en calcular
            submit_btn = page.locator("button:has-text('Berechnen'), button:has-text('Vergleichen'), button[type='submit']").first
            if await submit_btn.is_visible(timeout=2000):
                await submit_btn.click()

            await page.wait_for_timeout(4000)

            # Capturar TODAS las tarjetas/filas de tarifas resultantes
            cards = await page.locator("div[class*='tariff'], div[class*='card'], tr[class*='tariff']").all()

            for card in cards:
                try:
                    card_text = await card.inner_text()
                    if "Monat" not in card_text and "Grundpreis" not in card_text and "Arbeitspreis" not in card_text:
                        continue

                    # Extraer Título/Nombre de la tarifa
                    title = "Octopus Energy Tarif"
                    lines = [line.strip() for line in card_text.split('\n') if line.strip()]
                    for line in lines:
                        if "octopus" in line.lower() or "relax" in line.lower() or "basic" in line.lower():
                            title = line
                            break

                    # Extraer Abschlag / Cuota Mensual
                    monat_match = re.search(r"(\d+[,.]\d+)\s*€", card_text)
                    preis_monat = clean_float(monat_match.group(1)) if monat_match else 0.0

                    # Extraer Grundpreis
                    gp_match = re.search(r"Grundpreis:?\s*(\d+[,.]\d+)", card_text)
                    grundpreis = clean_float(gp_match.group(1)) if gp_match else 0.0

                    # Extraer Arbeitspreis
                    ap_match = re.search(r"Arbeitspreis:?\s*(\d+[,.]\d+)", card_text)
                    arbeitspreis = clean_float(ap_match.group(1)) if ap_match else 0.0

                    # Totales
                    preis_jahr = round(preis_monat * 12, 2) if preis_monat > 0 else round((kwh * (arbeitspreis / 100)) + (grundpreis * 12), 2)
                    ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

                    tarife_liste.append({
                        "provider": "Octopus Energy",
                        "tariff": title,
                        "arbeitspreis_ct": arbeitspreis,
                        "grundpreis_euro": grundpreis,
                        "preis_monat_euro": preis_monat,
                        "preis_jahr_euro": preis_jahr,
                        "ersparnis_jahr_euro": ersparnis,
                        "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                        "link": page.url
                    })
                except Exception as ie:
                    print(f"Error procesando tarifa Octopus: {ie}")

        except Exception as e:
            print(f"Energiemarie Scrape Error: {e}")

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
