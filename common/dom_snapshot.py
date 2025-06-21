from playwright.async_api import Page
from common import state

import httpx
from config import API_BASE_URL, API_KEY

async def upload_snapshot_to_api(url: str, dom_json: str):
    """Uploads full raw DOM JSON to the selector snapshot endpoint."""
    endpoint = f"{API_BASE_URL}/api/selectoranalysis/submit"
    headers = {"x-api-key": API_KEY}

    payload = {
        "url": url,
        "domJson": dom_json  # full string blob
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

async def collect_snapshot():
    page = state.active_page
    if not page:
        return {"error": "No active page"}

    root = await page.query_selector("body")
    if not root:
        return {"error": "No body element found"}

    snapshot_tree = await walk_dom_tree(root)
    state.active_dom_snapshot = snapshot_tree  # now a full tree

    return {
        "url": page.url,
        "timestamp": page.context._loop.time(),
        "source": "agent-tree-snapshot",
        "dom": snapshot_tree,
    }


async def walk_dom_tree(el, depth=0, max_depth=5):
    if depth > max_depth:
        return None

    try:
        tag = await el.evaluate("e => e.tagName.toLowerCase()")
        id_val = await el.get_attribute("id")
        class_list = await el.evaluate("e => Array.from(e.classList)")
        attrs = await el.evaluate("e => Object.fromEntries(Array.from(e.attributes).map(a => [a.name, a.value]))")
        text = (await el.text_content() or "").strip()
        box = await el.bounding_box()
        is_visible = await el.is_visible()

        # Skip hidden or tiny elements
        if not is_visible or (box and (box["width"] < 2 or box["height"] < 2)):
            return None

        node = {
            "tag": tag,
            "id": id_val or "",
            "classes": class_list,
            "attributes": attrs,
            "text": text,
            "boundingBox": box,
            "isClickable": tag in ["a", "button"] or "clickable" in " ".join(class_list).lower(),
            "isFormField": tag in ["input", "select", "textarea"],
            "children": [],
        }

        children = await el.query_selector_all(":scope > *")
        for child in children:
            child_node = await walk_dom_tree(child, depth + 1, max_depth)
            if child_node:
                node["children"].append(child_node)

        return node

    except Exception:
        return None
