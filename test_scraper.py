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
            await page.goto("https://octopusenergy.de/signup/1-start", wait_until="domcontentloaded", timeout=25000)

            # Cookie Banner
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), #onetrust-accept-btn-handler").first
                if await cookie_btn.is_visible(timeout=2000):
                    await cookie_btn.click()
            except Exception:
                pass

            # Rellenar PLZ
            plz_input = page.locator("input[placeholder*='PLZ'], input[name*='postcode']").first
            if await plz_input.is_visible(timeout=3000):
                await plz_input.fill(str(plz))
                await page.wait_for_timeout(1000)

                # Manejo dinámico del campo Straße y Hausnummer
                street_input = page.locator("input[placeholder*='Straße'], input[name*='street']").first
                if await street_input.is_visible(timeout=3000):
                    await street_input.fill("a")
                    await page.wait_for_timeout(1500)
                    
                    # Seleccionar la primera sugerencia del autocompletado
                    suggestion = page.locator("li[role='option'], div[class*='suggestion'], ul li").first
                    if await suggestion.is_visible(timeout=2000):
                        await suggestion.click()
                    else:
                        await street_input.fill("Hauptstraße")

                # Número de casa
                number_input = page.locator("input[placeholder*='Nr'], input[name*='houseNumber']").first
                if await number_input.is_visible(timeout=2000):
                    await number_input.fill("1")

                # kWh / Consumo
                kwh_input = page.locator("input[placeholder*='kWh'], input[name*='kwh']").first
                if await kwh_input.is_visible(timeout=2000):
                    await kwh_input.fill("")
                    await kwh_input.fill(str(kwh))

                # Botón de consulta
                submit_btn = page.locator("button:has-text('Tarif finden'), button[type='submit']").first
                if await submit_btn.is_visible(timeout=2000):
                    await submit_btn.click()

                await page.wait_for_timeout(4000)

                # Capturar TODAS las tarjetas de tarifas de Octopus
                cards = await page.locator("div[class*='TariffCard'], div[class*='tariff-card'], div[class*='Card']").all()

                for card in cards:
                    try:
                        card_text = await card.inner_text()
                        if "Abschlag" not in card_text and "Grundpreis" not in card_text:
                            continue

                        # Título de la tarifa
                        title = "Octopus Tarif"
                        lines = [line.strip() for line in card_text.split('\n') if line.strip()]
                        for line in lines:
                            if "octopus" in line.lower() or "relax" in line.lower():
                                title = line
                                break

                        # Precios
                        monat_match = re.search(r"(\d+[,.]\d+)\s*€\s*\n?\s*Abschlag", card_text)
                        preis_monat = clean_float(monat_match.group(1)) if monat_match else 0.0

                        gp_match = re.search(r"Grundpreis:\s*(\d+[,.]\d+)", card_text)
                        grundpreis = clean_float(gp_match.group(1)) if gp_match else 0.0

                        ap_match = re.search(r"Arbeitspreis:\s*(\d+[,.]\d+)", card_text)
                        arbeitspreis = clean_float(ap_match.group(1)) if ap_match else 0.0

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
                        print(f"Octopus Card Error: {ie}")
        except Exception as e:
            print(f"Octopus Main Scrape Error: {e}")

        # ====================================================
        # 2. RABOT CHARGE
        # ====================================================
        try:
            rabot_url = f"https://funnel.rabot.energy/tariff-details?plz={plz}&consumption={kwh}&hasDevices=false"
            await page.goto(rabot_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)

            # Capturar TODAS las tarjetas de tarifas de Rabot (dynamic, comfort, fix)
            cards = await page.locator("div[class*='card'], div[class*='Tariff']").all()

            for card in cards:
                try:
                    card_text = await card.inner_text()
                    if "rabot." not in card_text.lower() and "pro Monat" not in card_text:
                        continue

                    title = "Rabot Charge Tarif"
                    for t_name in ["rabot.dynamic", "rabot.comfort", "rabot.fix"]:
                        if t_name in card_text.lower():
                            title = t_name
                            break

                    monat_match = re.search(r"(\d+[,.]\d+)\s*€\s*\n?.*pro Monat", card_text)
                    preis_monat = clean_float(monat_match.group(1)) if monat_match else 0.0

                    ap_match = re.search(r"Arbeitspreis.*?(\d+[,.]\d+)\s*ct", card_text)
                    arbeitspreis = clean_float(ap_match.group(1)) if ap_match else 0.0

                    gp_match = re.search(r"Grundpreis.*?(\d+[,.]\d+)\s*€", card_text)
                    grundpreis = clean_float(gp_match.group(1)) if gp_match else 0.0

                    preis_jahr = round(preis_monat * 12, 2)
                    ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

                    tarife_liste.append({
                        "provider": "Rabot Charge",
                        "tariff": title,
                        "arbeitspreis_ct": arbeitspreis,
                        "grundpreis_euro": grundpreis,
                        "preis_monat_euro": preis_monat,
                        "preis_jahr_euro": preis_jahr,
                        "ersparnis_jahr_euro": ersparnis,
                        "logo": "https://www.rabot.energy/wp-content/uploads/2025/07/Rabot-Energy-RGB-150dpi-Logo-schwarz-gruen-positiv-randlos.webp",
                        "link": rabot_url
                    })
                except Exception as ie:
                    print(f"Rabot Card Error: {ie}")
        except Exception as e:
            print(f"Rabot Main Scrape Error: {e}")

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
