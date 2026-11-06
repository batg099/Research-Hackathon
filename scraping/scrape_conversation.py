import json
import re
import time
import os
import requests
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup, NavigableString, Tag

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════

OUTPUT_FILE  = "conversations.json"
IMAGES_DIR   = "images"
COOKIES_FILE = "chatgpt_cookies.json"
WAIT_TIME    = 5

URLS_TO_SCRAPE = [
    "https://chatgpt.com/share/68efac85-7b0c-8005-8104-accd820ec4df",
    "https://chatgpt.com/share/68efac97-929c-8012-a0a3-8bd4cf1f8ed5",
    "https://chatgpt.com/share/68efa949-1b94-8011-9d52-5cd2c343a628",
    "https://chatgpt.com/share/68efac53-19d8-8003-a5c2-ac4b9bc72acd",
    "https://chatgpt.com/share/68efae64-6268-800b-a3b3-638aebd90bce",
    "https://chatgpt.com/share/68efb387-f170-8008-8c74-95a9126f1dd4",
    "https://chatgpt.com/share/68efdd3d-8568-8009-9f49-71a5d86a8170"
]

# Compteur global d'images (partagé sur toutes les conversations)
img_counter = 0


# ════════════════════════════════════════════════════════════════════════════
# UTILITAIRE : extraction de texte qui préserve les blocs de code
# ════════════════════════════════════════════════════════════════════════════

def get_text_with_code(element) -> str:
    parts = []
    seen  = set()

    def walk(node):
        if id(node) in seen:
            return
        seen.add(id(node))

        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                parts.append(text)

        elif isinstance(node, Tag):
            if node.name == "pre":
                lang = ""

                header_div = node.find("div", class_=lambda c: c and "font-medium" in c)
                if header_div:
                    lang = header_div.get_text().strip().lower()

                code_block = node.find(id="code-block-viewer")
                if code_block:
                    code_text = code_block.get_text().strip()
                else:
                    cm_content = node.find(class_=lambda c: c and "cm-content" in c)
                    if cm_content:
                        code_text = cm_content.get_text().strip()
                    else:
                        code_el = node.find("code")
                        if code_el:
                            classes = " ".join(code_el.get("class", []))
                            match = re.search(r'language-(\w+)', classes)
                            if match:
                                lang = match.group(1)
                            code_text = code_el.get_text().strip()
                        else:
                            code_text = node.get_text().strip()
                            known_langs = ["Javascript", "Typescript", "Python", "Bash",
                                           "Shell", "Json", "Html", "Css", "Sql", "Java",
                                           "Cpp", "Text"]
                            for kl in known_langs:
                                if code_text.startswith(kl):
                                    lang = kl.lower()
                                    code_text = code_text[len(kl):]
                                    break

                parts.append(f"\n```{lang}\n{code_text}\n```\n")

                for child in node.descendants:
                    seen.add(id(child))

            elif node.name == "img":
                src = (node.get("src") or node.get("data-src") or "").strip()
                if not src:
                    srcset = node.get("srcset", "").strip()
                    if srcset:
                        src = srcset.split()[0]
                # Garde uniquement les images uploadées par l'utilisateur
                if src and "oaiusercontent" in src:
                    parts.append(f"[IMAGE_SRC:{src}]")

            elif node.name == "br":
                parts.append(" ")

            else:
                for child in node.children:
                    walk(child)

    walk(element)

    result = ""
    for p in parts:
        if not p:
            continue
        if p.startswith("\n```"):
            result = result.rstrip(" ") + p
        else:
            result = result + (" " if result and not result.endswith("\n") else "") + p
    return result.strip()


# ════════════════════════════════════════════════════════════════════════════
# DÉTECTION DE PLATEFORME
# ════════════════════════════════════════════════════════════════════════════

def detect_platform(url: str) -> str:
    if "chatgpt.com" in url or "chat.openai.com" in url:
        return "chatgpt"
    if "claude.ai" in url:
        return "claude"
    if "gemini.google.com" in url or "bard.google.com" in url:
        return "gemini"
    if "copilot.microsoft.com" in url or "bing.com/chat" in url:
        return "copilot"
    if "mistral.ai" in url or "chat.mistral.ai" in url:
        return "mistral"
    if "perplexity.ai" in url:
        return "perplexity"
    return "generic"


# ════════════════════════════════════════════════════════════════════════════
# EXTRACTEURS PAR PLATEFORME
# ════════════════════════════════════════════════════════════════════════════

def _get_img_src(img) -> str:
    src = (img.get("src") or img.get("data-src") or "").strip()
    if not src:
        srcset = img.get("srcset", "").strip()
        if srcset:
            src = srcset.split()[0]
    return src


def extract_chatgpt(soup: BeautifulSoup) -> list:
    messages = []
    seen_ids = set()

    turn_els = soup.find_all("article")
    if not turn_els:
        turn_els = soup.find_all(
            attrs={"data-testid": lambda v: v and str(v).startswith("conversation-turn-")}
        )

    for turn_el in turn_els:
        if id(turn_el) in seen_ids:
            continue
        seen_ids.add(id(turn_el))

        role_raw = turn_el.get("data-message-author-role", "")

        if not role_raw:
            role_el  = turn_el.find(attrs={"data-message-author-role": True})
            role_raw = role_el.get("data-message-author-role", "") if role_el else ""

        if not role_raw:
            role_raw = turn_el.get("data-turn", "")

        if not role_raw:
            testid_el = turn_el.find(
                attrs={"data-testid": lambda v: v and ("user" in v.lower() or "assistant" in v.lower())}
            )
            if testid_el:
                val      = testid_el.get("data-testid", "").lower()
                role_raw = "user" if "user" in val else "assistant"

        if not role_raw:
            m = re.search(r"conversation-turn-(\d+)", turn_el.get("data-testid", ""))
            if m:
                role_raw = "user" if int(m.group(1)) % 2 == 1 else "assistant"

        if role_raw == "user":
            role = "user"
        elif role_raw in ("assistant", "tool"):
            role = "assistant"
        else:
            continue

        text = get_text_with_code(turn_el)

        inner_img_ids = {id(img) for img in turn_el.find_all("img")}
        parent_turn   = turn_el.find_parent(
            attrs={"data-testid": lambda v: v and "conversation-turn" in str(v)}
        )
        if parent_turn:
            for img in parent_turn.find_all("img"):
                if id(img) not in inner_img_ids:
                    src = _get_img_src(img)
                    if src and "oaiusercontent" in src:
                        text = (text + " " if text else "") + f"[IMAGE_SRC:{src}]"

        if text:
            messages.append({"role": role, "text": text})

    if not messages:
        for el in soup.find_all(attrs={"data-message-author-role": True}):
            role_raw = el.get("data-message-author-role", "")
            role     = "user" if role_raw == "user" else "assistant"
            text     = get_text_with_code(el)
            if text:
                messages.append({"role": role, "text": text})

    return messages


def extract_generic(soup: BeautifulSoup) -> list:
    messages = []
    seen     = set()

    role_attrs = [
        "data-role", "data-author", "data-message-author-role",
        "data-turn-role", "data-testid", "role"
    ]

    for attr in role_attrs:
        for el in soup.find_all(attrs={attr: True}):
            val  = el.get(attr, "").lower()
            text = get_text_with_code(el)

            if not text or text in seen:
                continue

            if any(k in val for k in ["user", "human", "query"]):
                messages.append({"role": "user", "text": text})
                seen.add(text)
            elif any(k in val for k in ["assistant", "bot", "ai", "model", "response"]):
                messages.append({"role": "assistant", "text": text})
                seen.add(text)

    return messages


EXTRACTORS = {
    "chatgpt": extract_chatgpt,
    "generic": extract_generic,
}

def extract_messages(soup: BeautifulSoup, url: str):
    platform  = detect_platform(url)
    extractor = EXTRACTORS.get(platform, extract_generic)
    messages  = extractor(soup)

    if not messages and platform != "generic":
        print(f"  ⚠️  Sélecteur '{platform}' vide, fallback générique...")
        messages = extract_generic(soup)

    return messages, platform


# ════════════════════════════════════════════════════════════════════════════
# IMAGES : téléchargement
# ════════════════════════════════════════════════════════════════════════════

def get_image_extension(content_type: str) -> str:
    mapping = {
        "image/jpeg": "jpg",
        "image/png":  "png",
        "image/gif":  "gif",
        "image/webp": "webp",
    }
    return mapping.get(content_type.split(";")[0].strip(), "jpg")


def download_images_in_messages(messages: list, session: requests.Session, conv_id: int = 0, turn_id: int = 0) -> list:
    turn_img_counter = 0

    def replace_image(match):
        nonlocal turn_img_counter
        src = match.group(1).replace("&amp;", "&")
        if src.startswith("data:"):
            return match.group(0)
        try:
            r = session.get(src, timeout=15)
            r.raise_for_status()
            ext = get_image_extension(r.headers.get("Content-Type", ""))
            turn_img_counter += 1
            filename = f"img_{conv_id}_{turn_id}_{turn_img_counter}.{ext}"
            filepath = os.path.join(IMAGES_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(r.content)
            print(f"    📥 {filename}")
            return f"[{filepath}]"
        except Exception as e:
            print(f"    ❌ Échec image : {e}")
            return match.group(0)

    for msg in messages:
        msg["text"] = re.sub(r'\[IMAGE_SRC:([^\]]+)\]', replace_image, msg["text"])
    return messages

def get_requests_session(driver) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": driver.execute_script("return navigator.userAgent;")
    })
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain", ""))
    return session


# ════════════════════════════════════════════════════════════════════════════
# CONVERSION EN FORMAT TURNS
# ════════════════════════════════════════════════════════════════════════════

USER_TAG      = "Vous avez dit :"
ASSISTANT_TAG = "ChatGPT a dit :"

def messages_to_turns(messages: list) -> list:
    turns = []
    user_buf = None

    for msg in messages:
        if msg["role"] == "user":
            user_buf = msg["text"]
        elif msg["role"] == "assistant" and user_buf is not None:
            turns.append({
                "Turn": {
                    "Turn_id": len(turns) + 1,
                    "User":      f"{USER_TAG} {user_buf}",
                    "Assistant": f"{ASSISTANT_TAG} {msg['text']}",
                }
            })
            user_buf = None

    return turns


# ════════════════════════════════════════════════════════════════════════════
# DRIVER
# ════════════════════════════════════════════════════════════════════════════

def create_driver():
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = uc.Chrome(options=options, headless=False)
    driver.set_script_timeout(60)      # ← ajoute
    driver.set_page_load_timeout(60)   # ← ajoute
    return driver


# ════════════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def scrape_conversations(urls: list) -> list:
    driver  = create_driver()
    results = []

    # ── Injection des cookies ────────────────────────────────────────────────
    print("Navigation sur chatgpt.com pour injection des cookies...")
    driver.get("https://chatgpt.com")
    time.sleep(5)

    if os.path.exists(COOKIES_FILE):
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        injected = 0
        for cookie in cookies:
            clean = {k: v for k, v in cookie.items()
                     if k not in ("sameSite", "hostOnly", "storeId", "id", "session")}
            if "chatgpt.com" not in clean.get("domain", "") and "openai.com" not in clean.get("domain", ""):
                continue
            try:
                driver.add_cookie(clean)
                injected += 1
            except Exception as e:
                print(f"  ⚠️  Cookie ignoré ({clean.get('name', '?')}): {e}")
        print(f"  🍪 {injected} cookies injectés")
    else:
        print(f"  ⚠️  '{COOKIES_FILE}' introuvable — images non authentifiées")
    # ────────────────────────────────────────────────────────────────────────

    for idx, url in enumerate(urls, start=1):
        print(f"\n[{idx}/{len(urls)}] {url}")
        try:
            driver.get(url)

            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "article, [data-message-author-role]")
                    )
                )
            except Exception:
                print("  ⚠️  Timeout attente React")

            # Scroll pour déclencher le lazy-loading des images
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(2)

            # ── outerHTML pour avoir le DOM complet avec les images ──
# Remplace
            html = driver.execute_script("return document.documentElement.outerHTML;")

            # Par
            try:
                html = driver.execute_script("return document.documentElement.outerHTML;")
            except Exception:
                print("  ⚠️  Timeout outerHTML, fallback page_source")
                html = driver.page_source
            soup = BeautifulSoup(html, "lxml")

            messages, platform = extract_messages(soup, url)

            # ── Téléchargement des images ──
            session  = get_requests_session(driver)
            # D'abord groupe en turns, puis télécharge avec les bons ids
            turns_raw = messages_to_turns(messages)
            for turn_obj in turns_raw:
                turn = turn_obj["Turn"]
                turn_id = turn["Turn_id"]
                for key in ("User", "Assistant"):
                    # Crée un faux message pour passer dans download
                    fake = [{"role": "user", "text": turn[key]}]
                    fake = download_images_in_messages(fake, session, conv_id=idx, turn_id=turn_id)
                    turn[key] = fake[0]["text"]
            turns = turns_raw

            turns = messages_to_turns(messages)

            print(f"  Platform : {platform}")
            print(f"  Turns    : {len(turns)}")

            results.append({
                "Id":       idx,
                "Title":    driver.title,
                "Url":      url,
                "Platform": platform,
                "Turns":    turns,
            })
            print(f"  ✅ {driver.title[:60]}")

        except Exception as e:
            print(f"  ❌ Erreur : {e}")

    driver.quit()
    return results


def main():
    conversations = scrape_conversations(URLS_TO_SCRAPE)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(conversations, f, ensure_ascii=False, indent=2)
    print(f"\n✅ {len(conversations)} conversations sauvegardées dans '{OUTPUT_FILE}'")


if __name__ == "__main__":
    main()