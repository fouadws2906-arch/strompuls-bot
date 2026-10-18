import json
import urllib.request
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def fetch_json(url: str):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return json.loads(response.read().decode())
    except Exception as e:
        print(f"Error al consultar {url}: {e}")
    return None

@app.get("/scrape")
async def get_tarife(plz: str = "10115", kwh: int = 1500):
    tarife_liste = []
    referenz_preis = (kwh * 0.38) + (12.50 * 12)

    # 1. RABOT CHARGE
    rabot_api_url = f"https://api.rabot.energy/v1/tariffs/calculator?plz={plz}&consumption={kwh}"
    data_rabot = fetch_json(rabot_api_url)
    
    if data_rabot:
        rab_ap = float(data_rabot.get("workingPrice", 33.32))
        rab_gp = float(data_rabot.get("basePrice", 10.28))
    else:
        rab_ap, rab_gp = 33.32, 10.28

    rab_jahr = round((kwh * (rab_ap / 100)) + (rab_gp * 12), 2)
    rab_monat = round(rab_jahr / 12, 2)
    rabot_url = f"https://funnel.rabot.energy/tariff-details?plz={plz}&consumption={kwh}&hasDevices=false"

    tarife_liste.append({
        "provider": "Rabot Charge",
        "tariff": "rabot.dynamic",
        "arbeitspreis_ct": rab_ap,
        "grundpreis_euro": rab_gp,
        "preis_monat_euro": rab_monat,
        "preis_jahr_euro": rab_jahr,
        "ersparnis_jahr_euro": round(max(0, referenz_preis - rab_jahr), 2),
        "logo": "https://www.rabot.energy/wp-content/uploads/2025/07/Rabot-Energy-RGB-150dpi-Logo-schwarz-gruen-positiv-randlos.webp",
        "link": rabot_url
    })

    # 2. OCTOPUS ENERGY
    oct_api_url = f"https://octopusenergy.de/api/v2/tariffs?postcode={plz}&kwh={kwh}"
    data_oct = fetch_json(oct_api_url)
    
    if data_oct:
        oct_ap = float(data_oct.get("unit_rate", 34.62))
        oct_gp = float(data_oct.get("standing_charge", 15.51))
    else:
        oct_ap, oct_gp = 34.62, 15.51

    oct_jahr = round((kwh * (oct_ap / 100)) + (oct_gp * 12), 2)
    oct_monat = round(oct_jahr / 12, 2)
    octopus_url = f"https://octopusenergy.de/signup/1-start?postcode={plz}&kwh={kwh}"

    tarife_liste.append({
        "provider": "Octopus Energy",
        "tariff": "octopus relax12",
        "arbeitspreis_ct": oct_ap,
        "grundpreis_euro": oct_gp,
        "preis_monat_euro": oct_monat,
        "preis_jahr_euro": oct_jahr,
        "ersparnis_jahr_euro": round(max(0, referenz_preis - oct_jahr), 2),
        "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
        "link": octopus_url
    })

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
