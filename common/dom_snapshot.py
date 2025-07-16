from playwright.async_api import Page
from common import state
import httpx
from common.config import API_BASE_URL, API_KEY
from bs4 import BeautifulSoup

async def upload_snapshot_to_api(url: str, html: str):
    """Uploads full HTML snapshot to the selector snapshot endpoint."""
    endpoint = f"{API_BASE_URL}/api/selectoranalysis/submit"
    headers = {"x-api-key": API_KEY}

    payload = {
        "url": url,
        "domHtml": html  # send as HTML string
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.status_code == 200:
                print("Snapshot uploaded to blob:", response.json().get("file"))
            else:
                print("Failed to upload snapshot:", response.status_code, response.text)
        except Exception as ex:
            print("Exception during snapshot upload:", str(ex))

def find_element_by_text_and_tag(html: str, target_text: str, target_tag: str, target_classes: list[str]):
    """Searches DOM for a tag with given text and classes."""
    soup = BeautifulSoup(html, "html.parser")
    elements = soup.find_all(target_tag)

    for el in elements:
        text = el.get_text(strip=True)
        classes = el.get("class", [])
        if text == target_text.strip() and set(target_classes).issubset(set(classes or [])):
            return el

    return None


