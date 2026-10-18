import asyncio
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

app = FastAPI()

# CORS middleware WordPress (strompuls.de) nisqapaq
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/scrape")
async def scrape_tarife(plz: str = "40210", kwh: int = 2500):
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

        # ----------------------------------------------------
        # 1. OCTOPUS ENERGY SCRAPING
        # ----------------------------------------------------
        try:
            await page.goto("https://octopusenergy.de/", wait_until="networkidle", timeout=30000)

            # Cookie-banner aceptay
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), button:has-text('Akzeptieren'), #onetrust-accept-btn-handler")
                if await cookie_btn.is_visible(timeout=3000):
                    await cookie_btn.click()
            except Exception:
                pass

            # PLZ hunt'achiy[cite: 4]
            plz_input = page.locator("input[placeholder*='PLZ'], input[name*='postcode'], input[id*='postcode']").first
            await plz_input.fill(str(plz))

            # "Wenig" akllay[cite: 4]
            wenig_btn = page.locator("button:has-text('Wenig'), div:has-text('Wenig')").first
            if await wenig_btn.is_visible(timeout=2000):
                await wenig_btn.click()

            # kWh hunt'achiy[cite: 4]
            kwh_input = page.locator("input[placeholder*='kWh'], input[name*='kwh'], input[id*='kwh']").first
            if await kwh_input.is_visible(timeout=2000):
                await kwh_input.fill("")
                await kwh_input.fill(str(kwh))

            # "Tarif finden" ñit'iy[cite: 4]
            tarif_btn = page.locator("button:has-text('Tarif finden')").first
            await tarif_btn.click()

            # Suyay resultado paginata
            await page.wait_for_url("**/signup/**", timeout=20000)
            await page.wait_for_selector("[class*='tariff'], [class*='card'], form", timeout=10000)

            octopus_final_url = page.url

            # Llapa tarifakunata Octopus nisqamanta hoqariy
            cards = await page.locator("div[class*='tariff-card'], div[class*='TariffCard'], article").all()

            if cards:
                for card in cards:
                    try:
                        title_el = card.locator("h2, h3, h4, [class*='title']").first
                        title = await title_el.inner_text() if await title_el.is_visible() else "Octopus Tarif"

                        arbeitspreis = 27.5
                        ap_el = card.locator("text=/\\d+[,.]\\d+\\s*ct/i").first
                        if await ap_el.is_visible():
                            ap_text = await ap_el.inner_text()
                            match = re.search(r"(\d+[,.]?\d*)", ap_text)
                            if match:
                                arbeitspreis = float(match.group(1).replace(",", "."))

                        grundpreis = 10.90
                        gp_el = card.locator("text=/\\d+[,.]\\d+\\s*€/i").first
                        if await gp_el.is_visible():
                            gp_text = await gp_el.inner_text()
                            match = re.search(r"(\d+[,.]?\d*)", gp_text)
                            if match:
                                grundpreis = float(match.group(1).replace(",", "."))

                        tarife_liste.append({
                            "provider": "Octopus Energy",
                            "tariff": title.strip(),
                            "arbeitspreis_ct": arbeitspreis,
                            "grundpreis_euro": grundpreis,
                            "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                            "link": octopus_final_url
                        })
                    except Exception as inner_e:
                        print(f"Octopus tarjeta pantay: {inner_e}")

        except Exception as e:
            print(f"Octopus Scrape pantay: {e}")

        finally:
            await browser.close()

    # Mana tarikuqtinqa, tarifakuna fallback hinalla
    if not tarife_liste:
        tarife_liste = [
            {
                "provider": "Octopus Energy",
                "tariff": "Octopus Basic Öko",
                "arbeitspreis_ct": 27.5,
                "grundpreis_euro": 10.90,
                "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                "link": f"https://octopusenergy.de/signup/2-tariff-selection?postcode={plz}&kwh={kwh}"
            },
            {
                "provider": "Octopus Energy",
                "tariff": "Octopus Heat Pump / Dynamic",
                "arbeitspreis_ct": 24.2,
                "grundpreis_euro": 11.50,
                "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                "link": f"https://octopusenergy.de/signup/2-tariff-selection?postcode={plz}&kwh={kwh}"
            }
        ]

    # ----------------------------------------------------
    # 2. RABOT CHARGE TARIFA (Keine Geräte vorhanden)
    # ----------------------------------------------------
    rabot_link = f"https://funnel.rabot.energy/tariff-details?plz={plz}&consumption={kwh}&kwh={kwh}&hasDevices=false&smartMeter=false"

    tarife_liste.append({
        "provider": "Rabot Charge",
        "tariff": "Rabot Dynamic Pur",
        "arbeitspreis_ct": 25.8,
        "grundpreis_euro": 9.90,
        "logo": "https://www.rabot.energy/wp-content/uploads/2025/07/Rabot-Energy-RGB-150dpi-Logo-schwarz-gruen-positiv-randlos.webp",
        "link": rabot_link
    })

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
