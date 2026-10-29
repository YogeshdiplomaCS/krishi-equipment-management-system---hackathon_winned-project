import os
import requests
from dotenv import load_dotenv
load_dotenv()

class IntegrationError(ValueError):
    pass

def get_weather(location):
    key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    if not key:
        raise IntegrationError(".env ನಲ್ಲಿ OPENWEATHER_API_KEY ಸೇರಿಸಿ, ಅಥವಾ device/map location ಬಳಸಿ.")
    response = requests.get("https://api.openweathermap.org/data/2.5/weather",
        params={"q": location, "appid": key, "units": "metric"}, timeout=15)
    if response.status_code == 404:
        raise IntegrationError("Location ಕಂಡುಬಂದಿಲ್ಲ. ಉದಾ: Nanjangud, Karnataka, India")
    try:
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise IntegrationError("Weather service ಈಗ ಲಭ್ಯವಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.") from exc
    return {"location": f"{data['name']}, {data['sys'].get('country','')}", "temp": data['main']['temp'],
        "feels_like": data['main']['feels_like'], "humidity": data['main']['humidity'],
        "wind": data.get('wind', {}).get('speed', 0) * 3.6,
        "description": data['weather'][0]['description'].title(), "icon": data['weather'][0]['icon']}

def ask_agriculture_ai(question, language="English", context=""):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise IntegrationError("AI Assistant ಬಳಸಲು .env ನಲ್ಲಿ OPENROUTER_API_KEY ಸೇರಿಸಿ.")
    model = os.getenv("OPENROUTER_MODEL", "openrouter/auto").strip()
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8501", "X-Title": "Krishi Equipment"},
            json={"model": model, "messages": [
                {"role": "system", "content": f"You are a careful agriculture and farm equipment assistant. Respond in {language}. Do not invent live weather or booking data. For pesticide safety, advise following product labels and local agricultural experts. {context}"},
                {"role": "user", "content": question}], "temperature": 0.3}, timeout=45)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.RequestException as exc:
        raise IntegrationError("AI service ಸಂಪರ್ಕವಾಗಲಿಲ್ಲ. API key/network ಪರಿಶೀಲಿಸಿ.") from exc

# Backwards-compatible name for the Streamlit app.
ask_ai = ask_agriculture_ai
