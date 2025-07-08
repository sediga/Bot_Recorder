import re
import os
import httpx
from typing import Optional, Tuple
from datetime import datetime
from bs4 import BeautifulSoup
from common import state

async def get_devtools_like_selector(el):
    path = []

    while el:
        tag = await el.evaluate("e => e.tagName.toLowerCase()")
        id_attr = await el.get_attribute("id")

        if id_attr:
            path.insert(0, f"#{id_attr}")
            break
        else:
            class_attr = await el.get_attribute("class") or ""
            class_selector = "." + ".".join(
                [c for c in class_attr.strip().split() if c]
            ) if class_attr else ""
            
            parent = await el.evaluate_handle("e => e.parentElement")
            siblings = await el.evaluate("""(e) => {
                const tag = e.tagName;
                return Array.from(e.parentElement?.children || []).filter(child => child.tagName === tag).length;
            }""")
            index = await el.evaluate("""(e) => {
                const tag = e.tagName;
                return Array.from(e.parentElement?.children || []).filter(child => child.tagName === tag).indexOf(e) + 1;
            }""")

            nth = f":nth-child({index})" if siblings and index > 0 else ""
            path.insert(0, f"{tag}{class_selector}{nth}")

        el = await el.evaluate_handle("e => e.parentElement")

    return " > ".join(path)

def normalize(text: Optional[str]) -> str:
    return (text or "").strip().lower().replace("\xa0", " ")


def text_matches(a: str, b: str) -> bool:
    return normalize(a) == normalize(b)


async def find_better_selector(payload: dict, html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    elements = soup.find_all(True)

    target_text = normalize(payload.get("innerText") or payload.get("elementText"))
    target_attrs = payload.get("attributes", {})
    target_id = target_attrs.get("id")
    target_name = target_attrs.get("name")
    target_type = target_attrs.get("type")
    target_classes = set(payload.get("classList") or [])

    best_match = None
    reason = ""

    for el in elements:
        tag = el.name.lower()
        el_id = el.get("id", "")
        el_name = el.get("name", "")
        el_aria = el.get("aria-label", "")
        el_testid = el.get("data-testid", "")
        el_type = el.get("type", "")
        el_classes = set(el.get("class", []) or [])
        el_text = normalize(el.get_text(strip=True))

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
        tag = best_match.name.lower()
        el_classes = best_match.get("class", []) or []
        text = best_match.get_text(strip=True)

        class_selector = (
            "." + ".".join([c for c in el_classes if re.match(r"^[a-zA-Z0-9_-]+$", c)])
        ) if el_classes else ""

        selector = f"{tag}{class_selector}"
        if text and len(text) < 80:
            selector += f':has-text("{text}")'

        return selector, reason or "Fallback selector"

    return "", "No reliable match found"


import os

async def validate_and_enrich_selector(payload: dict) -> dict:
    selector = payload.get("selector")
    if not selector:
        return {**payload, "valid": False, "reason": "Missing selector"}

    page = state.active_page
    if not page:
        return {**payload, "valid": False, "reason": "No active page"}

    try:
        loose_selector = loosen_selector(selector)
        el = await page.locator(loose_selector).first.element_handle()
        if not el:
            raise Exception("Element not found with loose selector")

        replay_selector = await build_resilient_selector(el)
        payload["replaySelector"] = replay_selector
        payload["valid"] = True
        payload["reason"] = "Resolved and enriched with replay-safe selector"

        if os.getenv("BOTFLOWS_ENABLE_AX", "true").lower() == "true":
            ax_snapshot = await page.accessibility.snapshot()
            name = payload.get("innerText") or payload.get("elementText")
            node = traverse_ax_tree(ax_snapshot, name.strip() if name else "")
            if node:
                payload["accessibility"] = {
                    "role": node.get("role"),
                    "name": node.get("name")
                }

        if os.getenv("BOTFLOWS_ENABLE_COLUMN_TYPE", "true").lower() == "true":
            if await is_inside_grid(el) and await is_header_cell(el):
                col_type = await infer_column_type(page, replay_selector)
                payload["inferredType"] = col_type

        return payload

    except Exception as e:
        return {**payload, "valid": False, "reason": f"Playwright error: {str(e)}"}

def traverse_ax_tree(node: dict, target_name: str) -> Optional[dict]:
    if not node or "name" not in node:
        return None

    if normalize(node.get("name", "")) == normalize(target_name):
        return node

    for child in node.get("children", []):
        found = traverse_ax_tree(child, target_name)
        if found:
            return found

    return None


def loosen_selector(selector: str) -> str:
    selector = re.sub(r":nth-of-type\(\d+\)", "", selector)

    if ":has-text" in selector and re.search(r'(?i)(columnheader|grid|header)', selector):
        text_match = re.search(r':has-text\(".*?"\)', selector)
        if text_match:
            return f'[role="columnheader"]{text_match.group(0)}'

    selector = re.sub(r"\.[a-zA-Z0-9_-]+", "", selector, count=2)
    return selector.strip()


async def build_resilient_selector(el):
    tag = await el.evaluate("el => el.tagName.toLowerCase()")
    id_attr = await el.get_attribute("id")
    testid = await el.get_attribute("data-testid")
    aria = await el.get_attribute("aria-label")
    name_attr = await el.get_attribute("name")
    text = (await el.inner_text()).strip()

    if id_attr:
        return f"#{id_attr}"
    if testid:
        return f'[data-testid="{testid}"]'
    if aria:
        return f'[aria-label="{aria}"]'
    if name_attr:
        return f'[name="{name_attr}"]'
    if text and len(text) < 80:
        return f"{tag}:has-text(\"{text}\")"

    class_attr = await el.get_attribute("class")
    if class_attr:
        class_parts = [c for c in class_attr.split() if re.match(r"^[a-zA-Z0-9_-]+$", c)]
        if class_parts:
            return f"{tag}." + ".".join(class_parts[:2])

    return tag


def to_pascal_case(s):
    return ''.join(word.capitalize() for word in re.split(r'[_\s]+', s))

def convert_keys_to_pascal(obj):
    if isinstance(obj, dict):
        return {to_pascal_case(k): convert_keys_to_pascal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_keys_to_pascal(i) for i in obj]
    return obj

async def call_selector_recovery_api(step: dict) -> list[dict]:
    payload = convert_keys_to_pascal(step)
    headers = {
        "Content-Type": "application/json",
        "x-api-key": "u42Q7gXgVx8fN1rLk9eJ0cGm5wYzA2dR"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            base_url = os.getenv("BOTFLOWS_API_BASE_URL", "http://localhost:5000")
            res = await client.post(f"{base_url}/api/selectoranalysis/resolve", json=payload, headers=headers)
            if res.status_code == 200:
                return res.json().get("selectors", [])
            print(f"Recovery API failed: {res.status_code} => {res.text}")
    except Exception as ex:
        print(f"Selector recovery failed: {ex}")
    
    return []

async def confirm_selector_worked(flow_id, step_index, original_selector, improved_selector):
    headers = {
        "Content-Type": "application/json",
        # "x-api-key": os.getenv("BOTFLOWS_API_KEY", "")
        "x-api-key": "u42Q7gXgVx8fN1rLk9eJ0cGm5wYzA2dR"
    }
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{os.getenv('BOTFLOWS_API_BASE', 'http://localhost:5000')}/api/selectoranalysis/confirm",
                json={
                    "flowId": flow_id,
                    "stepIndex": step_index,
                    "originalSelector": original_selector,
                    "improvedSelector": improved_selector
                },
                timeout=10, headers=headers
            )
            if res.status_code == 200:
                print("Confirmation sent and flow updated.")
            else:
                print(f"Confirm failed: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"Error confirming selector: {e}")

async def infer_column_type(page, column_selector: str, max_samples=5) -> str:
    try:
        # Find all header cell elements
        header_elements = await page.query_selector_all('[role="columnheader"], .MuiDataGrid-columnHeader')
        if not header_elements:
            return "unknown"

        # Get target column header text
        target_el = await page.locator(column_selector).first.element_handle()
        if not target_el:
            return "unknown"

        target_text = (await target_el.inner_text()).strip().lower()

        # Match index by text
        index = -1
        for idx, el in enumerate(header_elements):
            header_text = (await el.inner_text()).strip().lower()
            if header_text == target_text:
                index = idx
                break

        if index < 0:
            return "unknown"

        # Now get cells under that column
        cell_selector = f'[role="row"] [role="cell"]:nth-child({index + 1})'
        cells = await page.query_selector_all(cell_selector)
        if not cells:
            return "unknown"

        # Extract text from cells
        texts = []
        for cell in cells[:max_samples]:
            text = (await cell.inner_text()).strip()
            if text:
                texts.append(text)

        is_date = all(_looks_like_date(t) for t in texts if t)
        if is_date:
            return "date"

        is_number = all(_looks_like_number(t) for t in texts if t)
        if is_number:
            return "number"

        return "text"

    except Exception as e:
        print(f"Error inferring column type: {e}")
        return "unknown"
    
def _looks_like_date(text):
    try:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
            datetime.strptime(text, fmt)
            return True
    except ValueError:
        pass
    return False


def _looks_like_number(text):
    try:
        float(text.replace(",", ""))
        return True
    except ValueError:
        return False

async def is_header_cell(el) -> bool:
    if not el:
        return False

    return await el.evaluate("""
        (node) => {
            const tag = node.tagName?.toLowerCase() || '';
            const text = node.innerText?.toLowerCase() || '';
            const classes = node.className?.toLowerCase() || '';
            const role = node.getAttribute('role')?.toLowerCase() || '';

            return (
                tag === 'th' ||
                role === 'columnheader' ||
                text.includes('header') ||
                classes.includes('header')
            );
        }
    """)

async def is_inside_grid(el) -> bool:
    if not el:
        return False

    return await el.evaluate("""
        (node) => {
            while (node && node.parentElement) {
                node = node.parentElement;
                const tag = node.tagName.toLowerCase();
                const role = node.getAttribute('role') || '';
                const classes = node.className || '';

                if (
                    tag === 'table' || tag === 'grid' ||
                    tag.includes('grid') ||
                    classes.toLowerCase().includes('grid') ||
                    classes.toLowerCase().includes('datatable') ||
                    role.toLowerCase() === 'grid'
                ) {
                    return true;
                }
            }
            return false;
        }
    """)

