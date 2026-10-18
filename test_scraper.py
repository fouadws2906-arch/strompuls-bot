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
    """ Convierte texto numérico con formato alemán '44,35 €' o '34,62 ct/kWh' a float """
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

        # ====================================================
        # 1. OCTOPUS ENERGY
        # ====================================================
        try:
            await page.goto("https://octopusenergy.de/", wait_until="networkidle", timeout=30000)

            # Cookie Banner
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), #onetrust-accept-btn-handler")
                if await cookie_btn.is_visible(timeout=3000):
                    await cookie_btn.click()
            except Exception:
                pass

            # Rellenar PLZ y kWh
            plz_input = page.locator("input[placeholder*='PLZ'], input[name*='postcode']").first
            await plz_input.fill(str(plz))

            wenig_btn = page.locator("button:has-text('Wenig'), div:has-text('Wenig')").first
            if await wenig_btn.is_visible(timeout=2000):
                await wenig_btn.click()

            kwh_input = page.locator("input[placeholder*='kWh'], input[name*='kwh']").first
            if await kwh_input.is_visible(timeout=2000):
                await kwh_input.fill("")
                await kwh_input.fill(str(kwh))

            await page.locator("button:has-text('Tarif finden')").first.click()

            await page.wait_for_url("**/signup/**", timeout=20000)
            await page.wait_for_selector("text=/Abschlag pro Monat|Grundpreis/i", timeout=10000)

            octopus_final_url = page.url
            cards = await page.locator("div[class*='TariffCard'], div[class*='tariff-card'], div[class*='Card']").all()

            for card in cards:
                try:
                    card_text = await card.inner_text()
                    if "Abschlag" not in card_text and "Grundpreis" not in card_text:
                        continue

                    # Extraer Nombre (ej: octopus relax24, octopus relax12)
                    title = "Octopus Tarif"
                    lines = [line.strip() for line in card_text.split('\n') if line.strip()]
                    for line in lines:
                        if "octopus" in line.lower() or "relax" in line.lower():
                            title = line
                            break

                    # Extraer Cuota Mensual / Abschlag (ej: 44,35 €)
                    preis_monat = 0.0
                    monat_match = re.search(r"(\d+[,.]\d+)\s*€\s*\n?\s*Abschlag", card_text)
                    if monat_match:
                        preis_monat = clean_float(monat_match.group(1))

                    # Extraer Grundpreis (ej: 15,51 €/Monat)
                    grundpreis = 0.0
                    gp_match = re.search(r"Grundpreis:\s*(\d+[,.]\d+)", card_text)
                    if gp_match:
                        grundpreis = clean_float(gp_match.group(1))

                    # Extraer Arbeitspreis (ej: 34,62 ct/kWh)
                    arbeitspreis = 0.0
                    ap_match = re.search(r"Arbeitspreis:\s*(\d+[,.]\d+)", card_text)
                    if ap_match:
                        arbeitspreis = clean_float(ap_match.group(1))

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
                        "link": octopus_final_url
                    })
                except Exception as inner_e:
                    print(f"Error procesando tarjeta Octopus: {inner_e}")

        except Exception as e:
            print(f"Octopus Scrape Error: {e}")

        # ====================================================
        # 2. RABOT CHARGE
        # ====================================================
        try:
            rabot_direct_url = f"https://funnel.rabot.energy/tariff-details?plz={plz}&consumption={kwh}&hasDevices=false"
            await page.goto(rabot_direct_url, wait_until="networkidle", timeout=20000)

            try:
                rabot_cookie = page.locator("button:has-text('Akzeptieren'), button:has-text('Alle akzeptieren')").first
                if await rabot_cookie.is_visible(timeout=3000):
                    await rabot_cookie.click()
            except Exception:
                pass

            await page.wait_for_selector("text=/pro Monat|Arbeitspreis/i", timeout=15000)

            # Buscar todas las tarjetas de Rabot (rabot.dynamic, rabot.comfort, rabot.fix)
            cards = await page.locator("div[class*='card'], div[class*='Tariff'], div[class*='tariff']").all()

            for card in cards:
                try:
                    card_text = await card.inner_text()
                    if "rabot." not in card_text.lower() and "pro Monat" not in card_text:
                        continue

                    # Extraer Nombre (ej: rabot.dynamic, rabot.comfort, rabot.fix)
                    title = "Rabot Charge Tarif"
                    for t_name in ["rabot.dynamic", "rabot.comfort", "rabot.fix"]:
                        if t_name in card_text.lower():
                            title = t_name
                            break

                    # Extraer Cuota Mensual / Ø pro Monat (ej: 51,94 €)
                    preis_monat = 0.0
                    monat_match = re.search(r"(\d+[,.]\d+)\s*€\s*\n?.*pro Monat", card_text)
                    if monat_match:
                        preis_monat = clean_float(monat_match.group(1))

                    # Extraer Arbeitspreis (ej: 33,32 ct/kWh)
                    arbeitspreis = 0.0
                    ap_match = re.search(r"Arbeitspreis.*?(\d+[,.]\d+)\s*ct", card_text)
                    if ap_match:
                        arbeitspreis = clean_float(ap_match.group(1))

                    # Extraer Grundpreis (ej: 10,28 €/Monat)
                    grundpreis = 0.0
                    gp_match = re.search(r"Grundpreis.*?(\d+[,.]\d+)\s*€", card_text)
                    if gp_match:
                        grundpreis = clean_float(gp_match.group(1))

                    # Extraer Ersparnis (ej: 9,86 €/Monat -> x12 para año)
                    ersparnis = 0.0
                    ersp_match = re.search(r"Ersparnis.*?(\d+[,.]\d+)\s*€", card_text)
                    if ersp_match:
                        ersparnis = round(clean_float(ersp_match.group(1)) * 12, 2)

                    preis_jahr = round(preis_monat * 12, 2)

                    tarife_liste.append({
                        "provider": "Rabot Charge",
                        "tariff": title,
                        "arbeitspreis_ct": arbeitspreis,
                        "grundpreis_euro": grundpreis,
                        "preis_monat_euro": preis_monat,
                        "preis_jahr_euro": preis_jahr,
                        "ersparnis_jahr_euro": ersparnis,
                        "logo": "https://www.rabot.energy/wp-content/uploads/2025/07/Rabot-Energy-RGB-150dpi-Logo-schwarz-gruen-positiv-randlos.webp",
                        "link": rabot_direct_url
                    })
                except Exception as inner_e:
                    print(f"Error procesando tarjeta Rabot: {inner_e}")

        except Exception as e:
            print(f"Rabot Charge Scrape Error: {e}")

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
