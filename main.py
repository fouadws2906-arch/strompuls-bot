import os
import json
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/scrape")
async def scrape_tarife(plz: str = "10115", kwh: float = 1500.0):
    api_key = os.getenv("GROQ_API_KEY")
    tarife_liste = []

    # 1. Versuch: Live-Daten via HTTP & Groq KI holen
    if api_key:
        try:
            client = Groq(api_key=api_key)
            url = "https://energiemarie.de/stromanbieter/octopus-energy"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as http_client:
                response = await http_client.get(url, headers=headers)
                raw_text = response.text

            prompt = f"""
            Analysiere den Text und extrahiere alle Octopus Energy Stromtarife für PLZ {plz} und {kwh} kWh/Jahr.
            Antworte AUSSCHLIESSLICH als gültiges JSON:
            {{
              "tarife": [
                {{
                  "tariff": "Octopus Basic / Classic",
                  "arbeitspreis_ct": 31.50,
                  "grundpreis_euro": 11.40,
                  "preis_jahr_euro": 580.00
                }}
              ]
            }}
            Text:
            {raw_text[:5000]}
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
                if preis_jahr > 0:
                    preis_monat = round(preis_jahr / 12, 2)
                    ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)
                    tarife_liste.append({
                        "provider": "Octopus Energy",
                        "tariff": item.get("tariff", "Octopus Energy Tarif"),
                        "arbeitspreis_ct": float(item.get("arbeitspreis_ct", 30.50)),
                        "grundpreis_euro": float(item.get("grundpreis_euro", 10.90)),
                        "preis_monat_euro": preis_monat,
                        "preis_jahr_euro": preis_jahr,
                        "ersparnis_jahr_euro": ersparnis,
                        "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
                        "link": f"https://octopusenergy.de/signup/1-start?postcode={plz}&kwh={kwh}"
                    })
        except Exception as e:
            print(f"Scraper/KI Hinweis: {e}")

    # 2. Fallback: Berechne dynamische Octopus-Standardtarife, falls das Live-Parsing leer bleibt
    if not tarife_liste:
        # Typische Marktdaten für Octopus Energy
        ap_ct = 29.80  # ~29,80 ct/kWh Arbeitspreis
        gp_m = 11.50   # ~11,50 €/Monat Grundpreis
        
        preis_jahr = round((kwh * (ap_ct / 100)) + (gp_m * 12), 2)
        preis_monat = round(preis_jahr / 12, 2)
        referenz_preis_jahr = (kwh * 0.38) + (12.50 * 12)
        ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

        tarife_liste.append({
            "provider": "Octopus Energy",
            "tariff": "Octopus Basic Strom",
            "arbeitspreis_ct": ap_ct,
            "grundpreis_euro": gp_m,
            "preis_monat_euro": preis_monat,
            "preis_jahr_euro": preis_jahr,
            "ersparnis_jahr_euro": ersparnis,
            "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
            "link": f"https://octopusenergy.de/signup/1-start?postcode={plz}&kwh={kwh}"
        })

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": tarife_liste
    }
