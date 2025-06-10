from playwright.sync_api import sync_playwright
import json
import os
import threading
import keyboard  # install with: pip install keyboard

actions = []
recording = True

def record_action(event):
    if event["type"] == "click":
        selector = event.get("selector", "")
        actions.append({
            "action": "click",
            "selector": selector
        })
    # elif event["type"] == ""

def wait_for_enter():
    global recording
    input("\nPress Enter to stop recording...\n")
    recording = False

def main():
    global recording
    url = input("Enter URL to record actions: ").strip()
    if not url.startswith("http"):
        url = "https://" + url

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Inject script to record clicks
        page.expose_function("recordAction", lambda e: record_action(e))
        page.goto(url)

        page.evaluate("""
            () => {
                document.addEventListener('click', (event) => {
                    const path = event.composedPath();
                    const element = path.find(el => el.id || el.className || el.tagName);
                    console.log("click event receibed:", element);
                    if (!element) return;

                    const selector = element.id
                        ? `#${element.id}`
                        : element.className
                        ? `.${element.className.toString().replace(/\\s+/g, '.')}`
                        : element.tagName;

                    console.log("Received action:", selector);
                    window.recordAction({ type: 'click', selector });
                });
            }
        """)

        # Start Enter listener
        enter_thread = threading.Thread(target=wait_for_enter, daemon=True)
        enter_thread.start()

        print("Recording started...")

        while recording:
            pass

        browser.close()
        
    print("\nRecording stopped.\nActions recorded:")
    for a in actions:
        print(a)

    # Save to JSON file
    os.makedirs("recordings", exist_ok=True)
    with open("recordings/actions.json", "w") as f:
        json.dump(actions, f, indent=2)


if __name__ == "__main__":
    main()
