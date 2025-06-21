import re
import os
import httpx
from typing import Optional, Tuple, List
from common import state

def normalize(text: Optional[str]) -> str:
    return (text or "").strip().lower().replace("\xa0", " ")

def text_matches(a: str, b: str) -> bool:
    return normalize(a) == normalize(b)

def flatten_dom_tree(node: dict, acc: List[dict]) -> None:
    acc.append(node)
    for child in node.get("children", []):
        flatten_dom_tree(child, acc)

async def find_better_selector(payload: dict, snapshot_tree: dict) -> Tuple[str, str]:
    flat_snapshot = []
    flatten_dom_tree(snapshot_tree, flat_snapshot)

    target_text = normalize(payload.get("innerText") or payload.get("elementText"))
    target_attrs = payload.get("attributes", {})
    target_id = target_attrs.get("id")
    target_name = target_attrs.get("name")
    target_type = target_attrs.get("type")
    target_classes = set(payload.get("classList") or [])

    best_match = None
    reason = ""

    for el in flat_snapshot:
        tag = el.get("tag", "").lower()
        el_id = el.get("id", "")
        el_attrs = el.get("attributes", {})
        el_name = el_attrs.get("name", "")
        el_aria = el_attrs.get("aria-label", "")
        el_testid = el_attrs.get("data-testid", "")
        el_type = el_attrs.get("type", "")
        el_classes = set(el.get("classes", []))
        el_text = normalize(el.get("text", ""))

        if target_id and el_id == target_id:
            return f"#{el_id}", "Using id"
        if target_name and el_name == target_name:
            return f'[name="{el_name}"]', "Using name"
        if el_aria and text_matches(el_aria, target_text):
            return f'[aria-label="{el_aria}"]', "Using aria-label"
        if el_testid:
            return f'[data-testid="{el_testid}"]', "Using data-testid"

        if target_text and el_text and text_matches(el_text, target_text):
            best_match = best_match or el
            reason = "Using visible text"

        if target_text and el_classes.intersection(target_classes):
            best_match = best_match or el
            reason = "Using partial class + text match"

        if tag == "input" and target_type and el_type == target_type:
            best_match = best_match or el
            reason = "Using input type match"

    if best_match:
        tag = best_match["tag"].lower()
        el_id = best_match.get("id", "")
        el_classes = best_match.get("classes", [])
        text = best_match.get("text", "")

        class_selector = (
            "." + ".".join([c for c in el_classes if re.match(r"^[a-zA-Z0-9_-]+$", c)])
        ) if el_classes else ""

        selector = f"{tag}{class_selector}"
        if text and len(text) < 80:
            selector += f':has-text("{text}")'

        return selector, reason or "Fallback selector"

    return "", "No reliable match found"

async def validate_and_enrich_selector(payload: dict) -> dict:
    selector = payload.get("selector")
    action_type = payload.get("action")
    if not selector or not action_type:
        return {**payload, "valid": False, "reason": "Missing selector or action type"}

    page = state.active_page
    if not page:
        return {**payload, "valid": False, "reason": "No active page"}

    try:
        el = await page.locator(selector).element_handle()
        if el:
            return {**payload, "valid": True, "reason": "Selector resolved"}
    except Exception as e:
        return {**payload, "valid": False, "reason": f"Playwright error: {str(e)}"}

    snapshot = state.active_dom_snapshot
    if not snapshot:
        return {**payload, "valid": False, "reason": "No DOM snapshot"}

    improved_selector, reason = await find_better_selector(payload, snapshot)

    if improved_selector:
        payload["selector"] = improved_selector
        payload["improvedSelector"] = improved_selector
        return {**payload, "valid": True, "reason": f"Fallback selector used: {reason}"}

    return {**payload, "valid": False, "reason": "Failed to resolve or recover selector"}

# ✅ New method to call .NET API for selector resolution
async def call_selector_recovery_api(url: str, failed_selector: str, tag: str = "", text: str = "", el_id: str = "") -> str | None:
    payload = {
        "url": url,
        "originalSelector": failed_selector,
        "tag": tag,
        "text": text,
        "id": el_id
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            base_url = os.getenv("BOTFLOWS_API_BASE_URL", "http://localhost:5000")
            res = await client.post(f"{base_url}/api/selectoranalysis/resolve", json=payload)
            if res.status_code == 200:
                return res.json().get("bestMatch")
    except Exception as ex:
        print(f"Selector recovery failed: {ex}")
    return None
