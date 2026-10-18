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

        try:
            # ====================================================
            # 1. OCTOPUS ENERGY
            # ====================================================
            try:
                await page.goto("https://octopusenergy.de/", wait_until="domcontentloaded", timeout=20000)

                try:
                    cookie_btn = page.locator("button:has-text('Alle akzeptieren'), #onetrust-accept-btn-handler").first
                    if await cookie_btn.is_visible(timeout=2000):
                        await cookie_btn.click()
                except Exception:
                    pass

                plz_input = page.locator("input[placeholder*='PLZ'], input[name*='postcode']").first
                if await plz_input.is_visible(timeout=3000):
                    await plz_input.fill(str(plz))

                    wenig_btn = page.locator("button:has-text('Wenig'), div:has-text('Wenig')").first
                    if await wenig_btn.is_visible(timeout=1500):
                        await wenig_btn.click()

                    kwh_input = page.locator("input[placeholder*='kWh'], input[name*='kwh']").first
                    if await kwh_input.is_visible(timeout=1500):
                        await kwh_input.fill("")
                        await kwh_input.fill(str(kwh))

                    await page.locator("button:has-text('Tarif finden')").first.click()
                    await page.wait_for_timeout(3000)

                    cards = await page.locator("div[class*='TariffCard'], div[class*='tariff-card'], div[class*='Card']").all()

                    for card in cards:
                        try:
                            card_text = await card.inner_text()
                            if "Abschlag" not in card_text and "Grundpreis" not in card_text:
                                continue

                            title = "Octopus Tarif"
                            for line in card_text.split('\n'):
                                if "relax" in line.lower() or "octopus" in line.lower():
                                    title = line.strip()
                                    break

                            monat_match = re.search(r"(\d+[,.]\d+)\s*€", card_text)
                            preis_monat = clean_float(monat_match.group(1)) if monat_match else 44.35

                            gp_match = re.search(r"Grundpreis:?\s*(\d+[,.]\d+)", card_text)
                            grundpreis = clean_float(gp_match.group(1)) if gp_match else 15.51

                            ap_match = re.search(r"Arbeitspreis:?\s*(\d+[,.]\d+)", card_text)
                            arbeitspreis = clean_float(ap_match.group(1)) if ap_match else 34.62

                            preis_jahr = round(preis_monat * 12, 2)
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
                print(f"Octopus Main Error: {e}")

            # Fallback für Octopus
            if not any(t["provider"] == "Octopus Energy" for t in tarife_liste):
                oct_m = round((kwh * (34.62 / 100) + (15.51 * 12)) / 12, 2)
                oct_j = round(oct_m * 12, 2)
                tarife_liste.append({
                    "provider": "Octopus Energy",
                    "tariff": "octopus relax12",
                    "arbeitspreis_ct": 34.62,
                    "grundpreis_euro": 15.51,
                    "preis_monat_euro": oct_m,
                    "preis_jahr_euro": oct_j,
                    "ersparnis_jahr_euro": round(max(0, referenz_preis_jahr - oct_j), 2),
                    "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                    "link": f"https://octopusenergy.de/signup/1-start?postcode={plz}&kwh={kwh}"
                })

            # ====================================================
            # 2. RABOT CHARGE
            # ====================================================
            try:
                rabot_url = f"https://funnel.rabot.energy/tariff-details?plz={plz}&consumption={kwh}&hasDevices=false"
                await page.goto(rabot_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)

                cards = await page.locator("div[class*='card'], div[class*='Tariff']").all()

                for card in cards:
                    try:
                        card_text = await card.inner_text()
                        if "rabot." not in card_text.lower() and "Monat" not in card_text:
                            continue

                        title = "rabot.dynamic"
                        for t_name in ["rabot.dynamic", "rabot.comfort", "rabot.fix"]:
                            if t_name in card_text.lower():
                                title = t_name
                                break

                        monat_match = re.search(r"(\d+[,.]\d+)\s*€", card_text)
                        preis_monat = clean_float(monat_match.group(1)) if monat_match else 51.94

                        ap_match = re.search(r"(\d+[,.]\d+)\s*ct", card_text)
                        arbeitspreis = clean_float(ap_match.group(1)) if ap_match else 33.32

                        gp_match = re.search(r"Grundpreis.*?(\d+[,.]\d+)", card_text)
                        grundpreis = clean_float(gp_match.group(1)) if gp_match else 10.28

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
                print(f"Rabot Main Error: {e}")

            # Fallback für Rabot Charge
            if not any(t["provider"] == "Rabot Charge" for t in tarife_liste):
                rab_url = f"https://funnel.rabot.energy/tariff-details?plz={plz}&consumption={kwh}&hasDevices=false"
                rab_m = round((kwh * (33.32 / 100) + (10.28 * 12)) / 12, 2)
                rab_j = round(rab_m * 12, 2)
                tarife_liste.append({
                    "provider": "Rabot Charge",
                    "tariff": "rabot.dynamic",
                    "arbeitspreis_ct": 33.32,
                    "grundpreis_euro": 10.28,
                    "preis_monat_euro": rab_m,
                    "preis_jahr_euro": rab_j,
                    "ersparnis_jahr_euro": round(max(0, referenz_preis_jahr - rab_j), 2),
                    "logo": "https://www.rabot.energy/wp-content/uploads/2025/07/Rabot-Energy-RGB-150dpi-Logo-schwarz-gruen-positiv-randlos.webp",
                    "link": rab_url
                })

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
