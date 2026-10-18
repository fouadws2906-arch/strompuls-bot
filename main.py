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
    if not api_key:
        return {"status": "error", "message": "GROQ_API_KEY no configurada en Render."}

    client = Groq(api_key=api_key)
    tarife_liste = []

    # 1. Consultar directamente a la web de Octopus Energy con la PLZ y consumo real
    # Generamos la URL dinámica con los parámetros de la ubicación del usuario
    url = f"https://octopusenergy.de/signup/1-start?postcode={plz}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    raw_text = ""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as http_client:
            response = await http_client.get(url, headers=headers)
            raw_text = response.text
    except Exception as e:
        return {"status": "error", "message": f"Error consultando Octopus Energy: {str(e)}"}

    # 2. IA Groq analiza la información específica recuperada para esta PLZ y consumo
    prompt = f"""
    Extrae TODOS los tarifas de electricidad de Octopus Energy disponibles para la ubicación con PLZ {plz} y un consumo de {kwh} kWh/año.
    
    Reglas:
    1. Si hay varios tarifas (ej. Octopus Basic, OctoPlus, Octopus Loyal, Select+), debes extraer TODOS los que aparezcan.
    2. Calcula o extrae el precio anual total (`preis_jahr_euro`), el trabajo por kWh (`arbeitspreis_ct`) y el costo base mensual (`grundpreis_euro`).

    Responde ÚNICAMENTE en este formato JSON:
    {{
      "tarife": [
        {{
          "tariff": "Nombre exacto del tarifa",
          "arbeitspreis_ct": 28.50,
          "grundpreis_euro": 10.90,
          "preis_jahr_euro": 546.00
        }}
      ]
    }}

    Contenido obtenido de la página:
    {raw_text[:7000]}
    """

    try:
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
            
            # Si el modelo no devolvió el precio anual calculado pero sí los precios unitarios:
            if preis_jahr == 0 and item.get("arbeitspreis_ct", 0) > 0:
                ap = float(item.get("arbeitspreis_ct"))
                gp = float(item.get("grundpreis_euro", 0))
                preis_jahr = round((kwh * (ap / 100)) + (gp * 12), 2)

            if preis_jahr > 0:
                preis_monat = round(preis_jahr / 12, 2)
                ersparnis = round(max(0, referenz_preis_jahr - preis_jahr), 2)

                tarife_liste.append({
                    "provider": "Octopus Energy",
                    "tariff": item.get("tariff", "Octopus Energy Tarif"),
                    "arbeitspreis_ct": float(item.get("arbeitspreis_ct", 0)),
                    "grundpreis_euro": float(item.get("grundpreis_euro", 0)),
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

    except Exception as e:
        return {"status": "error", "message": f"Error de IA: {str(e)}"}
