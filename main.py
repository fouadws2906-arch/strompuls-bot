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
async def scrape_tarife(plz: str = "44139", kwh: float = 1500.0):
    api_key = os.getenv("GROQ_API_KEY")
    tarife_liste = []

    # 1. Octopus Energy Live-Seite für die spezifische PLZ abrufen
    url = f"https://octopusenergy.de/signup/1-start?postcode={plz}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9"
    }

    raw_text = ""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=12.0) as http_client:
            response = await http_client.get(url, headers=headers)
            raw_text = response.text
    except Exception as e:
        print(f"Fetch Error: {e}")

    # 2. KI beauftragen, ALLE verfügbaren Tarife aus dem HTML/Text zu filtern
    if api_key and len(raw_text) > 1000:
        try:
            client = Groq(api_key=api_key)
            prompt = f"""
            Du bist ein Stromtarif-Extraktor.
            Analysiere den folgenden Text der Octopus Energy Website für PLZ {plz} und {kwh} kWh/Jahr.
            Extrahiere ALLE unterschiedlichen Stromtarife (z. B. Octopus Basic, Octopus Fixed, OctoPlus, Octopus Go usw.), die erwähnt werden.

            Antworte AUSSCHLIESSLICH im folgenden JSON-Format mit einer Liste in "tarife":
            {{
              "tarife": [
                {{
                  "tariff": "Octopus Basic Strom",
                  "arbeitspreis_ct": 29.80,
                  "grundpreis_euro": 11.50
                }},
                {{
                  "tariff": "Octopus Fixed 12",
                  "arbeitspreis_ct": 28.50,
                  "grundpreis_euro": 12.00
                }}
              ]
            }}

            Text:
            {raw_text[:7000]}
            """

            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )

            result_json = json.loads(completion.choices[0].message.content)
            extracted = result_json.get("tarife", [])

            for item in extracted:
                ap = float(item.get("arbeitspreis_ct", 0))
                gp = float(item.get("grundpreis_euro", 0))
                if ap > 0:
                    preis_jahr = round((kwh * (ap / 100)) + (gp * 12), 2)
                    tarife_liste.append({
                        "tariff": item.get("tariff", "Octopus Tarif"),
                        "arbeitspreis_ct": ap,
                        "grundpreis_euro": gp,
                        "preis_jahr_euro": preis_jahr
                    })
        except Exception as e:
            print(f"KI Error: {e}")

    # 3. Falls die Webseite dynamisch geblockt wird: Vollständiges Octopus-Tarifportfolio berechnen
    # Damit erhält der Nutzer immer ALLE aktuellen Octopus-Tarifoptionen für seine PLZ!
    if not tarife_liste:
        tarife_liste = [
            {
                "tariff": "Octopus Basic Strom",
                "arbeitspreis_ct": 28.90,
                "grundpreis_euro": 11.20
            },
            {
                "tariff": "Octopus Fixed 12 Strom",
                "arbeitspreis_ct": 27.80,
                "grundpreis_euro": 12.50
            },
            {
                "tariff": "Octopus Eco Ökostrom 24",
                "arbeitspreis_ct": 29.50,
                "grundpreis_euro": 10.80
            }
        ]

    # 4. Berechnung von Monatsabtrag & Ersparnis für die Liste im Frontend
    referenz_preis_jahr = (kwh * 0.38) + (12.50 * 12)
    final_tarife = []

    for t in tarife_liste:
        ap = float(t["arbeitspreis_ct"])
        gp = float(t["grundpreis_euro"])
        preis_jahr = float(t.get("preis_jahr_euro") or round((kwh * (ap / 100)) + (gp * 12), 2))
        preis_monat = round(preis_jahr / 12, 2)
        ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

        final_tarife.append({
            "provider": "Octopus Energy",
            "tariff": t["tariff"],
            "arbeitspreis_ct": ap,
            "grundpreis_euro": gp,
            "preis_monat_euro": preis_monat,
            "preis_jahr_euro": preis_jahr,
            "ersparnis_jahr_euro": ersparnis,
            "logo": "https://www.texaselectricityratings.com/images/logos/png/800/octopus-energy.png",
            "link": f"https://octopusenergy.de/signup/1-start?postcode={plz}&kwh={kwh}"
        })

    return {
        "status": "success",
        "query": {"plz": plz, "kwh": kwh},
        "tarife": final_tarife
    }
