import requests


def web_search(query):
    from db import load_setting

    api_key = load_setting("web_search_api_key", "")

    if not api_key:
        return None

    try:
        url = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": api_key
        }

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()

        results = response.json()

        if "organic_results" not in results:
            return None

        search_text = ""
        for result in results["organic_results"][:3]:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            if title or snippet:
                search_text += f"- {title}: {snippet}\n"

        return search_text if search_text else None

    except requests.exceptions.Timeout:
        print("[Search] Request timed out")
        return None

    except requests.exceptions.ConnectionError:
        print("[Search] No internet connection")
        return None

    except Exception as e:
        print(f"[Search] Unexpected error: {e}")
        return None
