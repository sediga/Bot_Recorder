from typing import List, Dict
from playwright.async_api import Page
from common.selectorHelper import get_devtools_like_selector
import re

def is_clickable(el_data):
    tag = el_data.get("tagName", "").lower()
    role = el_data.get("attributes", {}).get("role", "")
    classes = " ".join(el_data.get("classList", [])).lower()
    return tag in ["button", "a"] or "clickable" in classes or role == "button"


def is_input_field(el_data):
    tag = el_data.get("tagName", "").lower()
    return tag in ["input", "textarea", "select"]


def compute_bbox_overlap(box1, box2):
    if not box1 or not box2:
        return 0.0

    x1 = max(box1["x"], box2["x"])
    y1 = max(box1["y"], box2["y"])
    x2 = min(box1["x"] + box1["width"], box2["x"] + box2["width"])
    y2 = min(box1["y"] + box1["height"], box2["y"] + box2["height"])

    if x2 < x1 or y2 < y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    area1 = box1["width"] * box1["height"]
    area2 = box2["width"] * box2["height"]
    union = area1 + area2 - intersection

    return intersection / union

import re

def is_dynamic_id(id_str: str) -> bool:
    if not id_str:
        return False

    # Heuristics: numeric suffix, UUID, timestamp-like, or hashy
    return (
        re.search(r"-\d{5,}$", id_str) or  # ends in long number
        re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", id_str) or  # UUID
        re.search(r"(19|20)\d{2}[01]\d[0-3]\d", id_str) or  # date like 20240711
        re.search(r"[a-z]{4,}[A-Z]{2,}[a-z0-9]{2,}", id_str)  # hash-style mix
    )

async def analyze_selector_failure(page: Page, selector_obj: dict, target_box=None) -> str:
    sel = selector_obj.get("selector", "")
    source = selector_obj.get("source", "")

    try:
        locator = page.locator(sel)
        count = await locator.count()

        if count == 0:
            return "no-match"
        if count == 1:
            el = locator.first
            visible = await el.is_visible()
            enabled = await el.is_enabled()
            if not visible:
                return "not-visible"
            if not enabled:
                return "disabled"
            # ✅ Bounding box check for potentially volatile selectors
            if target_box and source in ["id"]:
                try:
                    box = await el.bounding_box()
                    if box and compute_bbox_overlap(box, target_box) < 0.7:
                        return "bbox-mismatch"
                except:
                    return "bbox-error"
            return "maybe-ok"

        # MULTIPLE MATCHES — Try bounding box resolution
        if target_box:
            best_match = None
            best_score = 0
            for i in range(count):
                box = await locator.nth(i).bounding_box()
                if not box:
                    continue
                score = compute_bbox_overlap(box, target_box)
                if score > best_score:
                    best_score = score
                    best_match = i

            if best_score > 0.7:  # Threshold
                selector_obj["matchIndex"] = best_match
                selector_obj["replayable"] = True
                return "multiple-match-resolved"

        return "multiple-match"
    except Exception as e:
        return f"error: {str(e)}"


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\.\w+\{[^}]+\}", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_attribute_selectors(tag: str, attributes: dict, text: str = "") -> List[Dict]:
    selectors = []
    preferred_attrs = ["data-testid", "aria-label", "name", "title", "alt"]

    for attr in preferred_attrs:
        val = attributes.get(attr)
        if not val or not isinstance(val, str):
            continue

        safe_val = val.replace('"', '\\"').strip()
        score = 90 if attr in ["data-testid", "aria-label"] else 70

        selectors.append({
            "selector": f'[{attr}="{safe_val}"]',
            "source": f"attr:{attr}",
            "score": score
        })

        if tag:
            selectors.append({
                "selector": f'{tag}[{attr}="{safe_val}"]',
                "source": f"tag+attr:{attr}",
                "score": score + 5
            })

        if tag and text:
            selectors.append({
                "selector": f'{tag}[{attr}="{safe_val}"]:has-text("{text}")',
                "source": f"tag+attr+text:{attr}",
                "score": score + 10
            })

    return selectors


def build_class_selector(tag: str, class_list: List[str]) -> Dict:
    stable_classes = [c for c in class_list if not re.match(r"^(cdk|ng|mat)-", c)]
    if tag and stable_classes:
        return {
            "selector": f"{tag}." + ".".join(stable_classes),
            "source": "class",
            "score": 80
        }
    return None


def build_text_selectors(tag: str, text: str, class_list: List[str]) -> List[Dict]:
    if not tag or not text:
        return []

    stable_classes = [c for c in class_list if not re.match(r"^(cdk|ng|mat)-", c)]
    prominent_class = next((c for c in stable_classes if len(c) > 5), None)
    text = clean_text(text)

    selectors = [{
        "selector": f'{tag}:has-text("{text}")',
        "source": "has-text",
        "score": 60
    }]

    if prominent_class:
        selectors.append({
            "selector": f'{tag}.{prominent_class}:has-text("{text}")',
            "source": "has-text-combo",
            "score": 85
        })

    return selectors


async def generate_recovery_selectors(page: Page, step: dict) -> List[Dict]:
    tag = step.get("tagName", "")
    el_id = step.get("attributes", {}).get("id", "")
    text = step.get("elementText", "") or step.get("innerText", "")
    class_list = step.get("classList", [])
    attributes = step.get("attributes", {})
    target_box = step.get("boundingBox")

    candidate_selectors = []

    # ID-based selector
    if el_id and re.match(r"^[A-Za-z][-A-Za-z0-9_:.]*$", el_id):
        is_dynamic = is_dynamic_id(el_id)
        candidate_selectors.append({
            "selector": f'#{el_id}',
            "source": "id",
            "score": 70 if is_dynamic else 100,
            "isDynamicId": is_dynamic
        })
        
    # Attribute-based selectors
    candidate_selectors += build_attribute_selectors(tag, attributes, text)

    # Class-based selector
    class_sel = build_class_selector(tag, class_list)
    if class_sel:
        candidate_selectors.append(class_sel)

    # Text-based selectors
    candidate_selectors += build_text_selectors(tag, text, class_list)

    # DOM path fallback
    dom_path = step.get("selector") or step.get("domPath")
    if dom_path:
        candidate_selectors.append({
            "selector": dom_path,
            "source": "dom-path",
            "score": 40
        })

    # XPath fallback
    xpath = step.get("xpath") or (f'//*[@id="{el_id}"]' if el_id else "")
    if xpath:
        candidate_selectors.append({
            "selector": xpath,
            "source": "xpath",
            "score": 30
        })

    # Deduplicate
    seen = set()
    deduped = []
    for c in candidate_selectors:
        if c["selector"] not in seen:
            deduped.append(c)
            seen.add(c["selector"])

    # Validate and score
    validated = []
    for sel_obj in deduped:
        reason = await analyze_selector_failure(page, sel_obj, target_box)
        sel_obj["matchFailureReason"] = reason

        if reason == "maybe-ok":
            sel_obj["verified"] = True
            sel_obj["replayable"] = True
            sel_obj["score"] += 20
        elif reason == "multiple-match-resolved":
            sel_obj["verified"] = True
            sel_obj["replayable"] = True
            sel_obj["score"] += 10
        elif reason == "bbox-mismatch":
            sel_obj["verified"] = False
            sel_obj["replayable"] = False
            sel_obj["score"] -= 15
        elif reason == "bbox-error":
            sel_obj["verified"] = False
            sel_obj["replayable"] = False
            sel_obj["score"] -= 15
        elif reason.startswith("multiple-match"):
            sel_obj["verified"] = False
            sel_obj["replayable"] = False
            sel_obj["score"] -= 10
        elif reason.startswith("no-match") or "error" in reason:
            sel_obj["verified"] = False
            sel_obj["replayable"] = False
            sel_obj["score"] -= 20
        else:
            sel_obj["verified"] = False
            sel_obj["replayable"] = False

        validated.append(sel_obj)

    validated.sort(key=lambda x: (x["replayable"], x["score"]), reverse=True)
    return validated
