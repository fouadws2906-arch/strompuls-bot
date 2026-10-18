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

@app.get("/scrape")
async def scrape_tarife(plz: str = "10115", kwh: int = 1500):
    tarife_liste = []
    
    # Precio de referencia estándar (~38 ct/kWh + 12.50 €/mes) para calcular ahorro relativo
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
        # 1. OCTOPUS ENERGY (Scraping dinámico)
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

            # Formulario Octopus
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

            # Esperar a los resultados de Octopus
            await page.wait_for_url("**/signup/**", timeout=20000)
            await page.wait_for_selector("[class*='tariff'], [class*='card'], article", timeout=10000)

            octopus_final_url = page.url
            cards = await page.locator("div[class*='tariff-card'], div[class*='TariffCard'], article").all()

            for card in cards:
                try:
                    title_el = card.locator("h2, h3, h4, [class*='title']").first
                    title = await title_el.inner_text() if await title_el.is_visible() else "Octopus Strom"

                    arbeitspreis = 27.5
                    ap_el = card.locator("text=/\\d+[,.]\\d+\\s*ct/i").first
                    if await ap_el.is_visible():
                        match = re.search(r"(\d+[,.]?\d*)", await ap_el.inner_text())
                        if match:
                            arbeitspreis = float(match.group(1).replace(",", "."))

                    grundpreis = 10.90
                    gp_el = card.locator("text=/\\d+[,.]\\d+\\s*€/i").first
                    if await gp_el.is_visible():
                        match = re.search(r"(\d+[,.]?\d*)", await gp_el.inner_text())
                        if match:
                            grundpreis = float(match.group(1).replace(",", "."))

                    gesamt_jahr = round((kwh * (arbeitspreis / 100)) + (grundpreis * 12), 2)
                    gesamt_monat = round(gesamt_jahr / 12, 2)
                    ersparnis_jahr = round(max(0, referenz_preis_jahr - gesamt_jahr), 2)

                    tarife_liste.append({
                        "provider": "Octopus Energy",
                        "tariff": title.strip(),
                        "arbeitspreis_ct": arbeitspreis,
                        "grundpreis_euro": grundpreis,
                        "preis_jahr_euro": gesamt_jahr,
                        "preis_monat_euro": gesamt_monat,
                        "ersparnis_jahr_euro": ersparnis_jahr,
                        "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                        "link": octopus_final_url
                    })
                except Exception as inner_e:
                    print(f"Error procesando tarjeta Octopus: {inner_e}")

        except Exception as e:
            print(f"Octopus Scrape Error: {e}")

        # ====================================================
        # 2. RABOT CHARGE (Directo al Funnel con hasDevices=false)
        # ====================================================
        try:
            rabot_direct_url = f"https://funnel.rabot.energy/tariff-details?plz={plz}&consumption={kwh}&hasDevices=false"
            
            # Navegar directamente al funnel ya configurado
            await page.goto(rabot_direct_url, wait_until="networkidle", timeout=20000)

            # Aceptar cookies si aparecen
            try:
                rabot_cookie = page.locator("button:has-text('Akzeptieren'), button:has-text('Alle akzeptieren')").first
                if await rabot_cookie.is_visible(timeout=3000):
                    await rabot_cookie.click()
            except Exception:
                pass

            # Esperar a que se rendericen los precios dinámicos
            await page.wait_for_selector("text=/ct\\/kWh|€\\/Monat|Tarif/i", timeout=15000)

            rabot_ap = 25.8
            ap_el = page.locator("text=/\\d+[,.]\\d+\\s*ct/i").first
            if await ap_el.is_visible():
                match = re.search(r"(\d+[,.]?\d*)", await ap_el.inner_text())
                if match:
                    rabot_ap = float(match.group(1).replace(",", "."))

            rabot_gp = 9.90
            gp_el = page.locator("text=/\\d+[,.]\\d+\\s*€/i").first
            if await gp_el.is_visible():
                match = re.search(r"(\d+[,.]?\d*)", await gp_el.inner_text())
                if match:
                    rabot_gp = float(match.group(1).replace(",", "."))

            rabot_jahr = round((kwh * (rabot_ap / 100)) + (rabot_gp * 12), 2)
            rabot_monat = round(rabot_jahr / 12, 2)
            rabot_ersparnis = round(max(0, referenz_preis_jahr - rabot_jahr), 2)

            tarife_liste.append({
                "provider": "Rabot Charge",
                "tariff": "Rabot Dynamic Pur",
                "arbeitspreis_ct": rabot_ap,
                "grundpreis_euro": rabot_gp,
                "preis_jahr_euro": rabot_jahr,
                "preis_monat_euro": rabot_monat,
                "ersparnis_jahr_euro": rabot_ersparnis,
                "logo": "https://www.rabot.energy/wp-content/uploads/2025/07/Rabot-Energy-RGB-150dpi-Logo-schwarz-gruen-positiv-randlos.webp",
                "link": rabot_direct_url
            })

        except Exception as e:
            print(f"Rabot Charge Scrape Error: {e}")
            # Fallback en caso de que tarde más de lo debido en responder
            rabot_direct_url = f"https://funnel.rabot.energy/tariff-details?plz={plz}&consumption={kwh}&hasDevices=false"
            rabot_jahr = round((kwh * 0.258) + (9.90 * 12), 2)
            tarife_liste.append({
                "provider": "Rabot Charge",
                "tariff": "Rabot Dynamic Pur",
                "arbeitspreis_ct": 25.8,
                "grundpreis_euro": 9.90,
                "preis_jahr_euro": rabot_jahr,
                "preis_monat_euro": round(rabot_jahr / 12, 2),
                "ersparnis_jahr_euro": round(max(0, referenz_preis_jahr - rabot_jahr), 2),
                "logo": "https://www.rabot.energy/wp-content/uploads/2025/07/Rabot-Energy-RGB-150dpi-Logo-schwarz-gruen-positiv-randlos.webp",
                "link": rabot_direct_url
            })

        finally:
            await browser.close()

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
