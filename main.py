import os
import json
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq

app = FastAPI()

# CORS aktivieren, damit WordPress (strompuls.de) zugreifen darf
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/scrape")
async def get_tarife(plz: str = "10115", kwh: int = 1500):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"status": "error", "message": "GROQ_API_KEY fehlt in Render!"}

    client = Groq(api_key=api_key)
    
    # 1. Webseite/API von Energiemarie / Stromanbieter abrufen
    url = f"https://energiemarie.de/stromanbieter/octopus-energy"
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as http_client:
        try:
            response = await http_client.get(
                url, 
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            raw_html_text = response.text
        except Exception as e:
            return {"status": "error", "message": f"Fehler beim Laden der Seite: {str(e)}"}

    # 2. KI-Prompt aufbereiten (Text auf 5000 Zeichen kürzen, um Limits einzuhalten)
    prompt = f"""
    Du bist ein Datenextraktor für Stromtarife.
    Analysiere den folgenden Text/HTML-Ausschnitt für die PLZ {plz} und {kwh} kWh/Jahr.
    Extrahiere alle Stromtarife von Octopus Energy.

    Gib AUSSCHLIESSLICH ein gültiges JSON-Objekt in exakt diesem Format zurück:
    {{
      "tarife": [
        {{
          "tariff": "Name des Tarifs",
          "arbeitspreis_ct": 30.5,
          "grundpreis_euro": 10.0,
          "preis_jahr_euro": 600.0
        }}
      ]
    }}

    Text-Ausschnitt:
    {raw_html_text[:5000]}
    """

    # 3. Groq API abfragen (Verwendung des stabilen Modells llama-3.1-8b-instant)
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        ki_ausgabe = json.loads(completion.choices[0].message.content)
        raw_tarife = ki_ausgabe.get("tarife", [])

        # 4. Berechnungen für dein Frontend durchführen
        ergebnis = []
        referenz_preis_jahr = (kwh * 0.38) + (12.50 * 12) # Vergleichsmaßstab

        for item in raw_tarife:
            preis_jahr = float(item.get("preis_jahr_euro", 0))
            preis_monat = round(preis_jahr / 12, 2) if preis_jahr > 0 else 0
            ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

            ergebnis.append({
                "provider": "Octopus Energy",
                "tariff": item.get("tariff", "Octopus Energy Tarif"),
                "arbeitspreis_ct": float(item.get("arbeitspreis_ct", 0)),
                "grundpreis_euro": float(item.get("grundpreis_euro", 0)),
                "preis_monat_euro": preis_monat,
                "preis_jahr_euro": preis_jahr,
                "ersparnis_jahr_euro": ersparnis,
                "link": f"https://octopusenergy.de/signup/1-start?postcode={plz}&kwh={kwh}"
            })

        return {
            "status": "success",
            "query": {"plz": plz, "kwh": kwh},
            "tarife": ergebnis
        }

    except Exception as e:
        return {"status": "error", "message": f"KI-Extraktionsfehler: {str(e)}"}
