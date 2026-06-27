import os
import subprocess
import requests

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


# =============================
# MODEL CONFIGURATION
# =============================

PROVIDERS = {
    "ollama": {
        "label": "Ollama (Local)",
        "models": {
            "Llama 3.1 (8B)": "llama3.1:8b",
            "Llama 3.2 (3B)": "llama3.2",
            "Mistral (7B)": "mistral:7b",
        }
    },
    "groq": {
        "label": "Groq (Cloud)",
        "models": {
            "Llama 3.3 70B": "llama-3.3-70b-versatile",
            "Llama 3.1 8B": "llama-3.1-8b-instant",
            "Mixtral 8x7B": "mixtral-8x7b-32768",
            "Gemma 2 9B": "gemma2-9b-it",
        }
    }
}

CURRENT_PROVIDER = "groq"
CURRENT_MODEL = "llama-3.3-70b-versatile"


# =============================
# CORE LLM CALL
# =============================

def chat_completion(model, messages, provider=None):
    if provider is None:
        provider = CURRENT_PROVIDER

    if provider == "groq":
        if not GROQ_AVAILABLE:
            return "[Error] Groq package not installed. Run: pip install groq"

        from db import load_setting
        api_key = load_setting("groq_api_key", "")

        if not api_key:
            return "[Error] Groq API key not set. Open Settings to add it."

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content

    elif provider == "ollama":
        if not OLLAMA_AVAILABLE:
            return "[Error] Ollama package not installed."

        response = ollama.chat(
            model=model,
            messages=messages
        )
        return response["message"]["content"]

    else:
        return f"[Error] Unknown provider: {provider}"


# =============================
# PROFILE EXTRACTION
# =============================

def extract_and_save_profile(conversation_snippet):
    prompt = f"""
Read the following conversation and extract any facts about the user.

Only extract clear, specific facts. Examples:
- interests or hobbies
- what they are studying or working on
- preferences about how they like to communicate
- personal details they mentioned

Return each fact on a separate line in this exact format:
trait: value

If there are no clear facts, return: none

Conversation:
{conversation_snippet}
"""

    output = chat_completion(
        model=CURRENT_MODEL,
        messages=[{"role": "user", "content": prompt}]
    )

    output = output.strip()

    if output.lower() == "none":
        return

    if output.startswith("[Error]"):
        return

    from db import save_profile_facts
    save_profile_facts(output)


# =============================
# MODEL MANAGEMENT
# =============================

def set_provider_and_model(provider, model):
    global CURRENT_PROVIDER, CURRENT_MODEL
    CURRENT_PROVIDER = provider
    CURRENT_MODEL = model

    from db import save_setting
    save_setting("current_provider", provider)
    save_setting("current_model", model)


def load_saved_provider_and_model():
    global CURRENT_PROVIDER, CURRENT_MODEL

    from db import load_setting
    saved_provider = load_setting("current_provider", "groq")
    saved_model = load_setting("current_model", "llama-3.3-70b-versatile")

    if saved_provider in PROVIDERS:
        CURRENT_PROVIDER = saved_provider

    if saved_provider == "groq":
        CURRENT_MODEL = saved_model
    elif saved_provider == "ollama":
        available = get_available_local_models()
        model_base = saved_model.split(":")[0]
        if model_base in available:
            CURRENT_MODEL = saved_model
        else:
            print(f"Saved model {saved_model} not found locally. Using default.")
            CURRENT_MODEL = "llama3.1:8b"


# =============================
# OLLAMA UTILITIES
# =============================

def ensure_model(model_name):
    try:
        subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=True
        )
    except Exception as e:
        print(f"Could not pull model {model_name}: {e}")


def get_available_local_models():
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True
        )
        return result.stdout.lower()
    except Exception:
        return ""


# =============================
# CONNECTIVITY
# =============================

def is_online():
    try:
        requests.get("https://www.google.com", timeout=3)
        return True
    except Exception:
        return False
