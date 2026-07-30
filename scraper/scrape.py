"""
Unegui.mn - Орон сууц зарна ангиллын шинэ зарыг өдөр бүр татаж,
өмнө үзээгүй зарыг docs/index.html дээр жагсаана.

Ажиллах зарчим:
- data/seen_ids.json файлд өмнө нь харсан бүх зарын ID-г хадгална.
- Ажиллах бүрдээ эхний хэдэн хуудасны зарыг татаж, ID-г нь seen_ids.json-той
  харьцуулаад, шинэ (өмнө нь байгаагүй) зарыг олно.
- Шинэ зарыг docs/index.html-ийн эхэнд нэмнэ (GitHub Pages-ээр харагдана).
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.unegui.mn/l-hdlh/l-hdlh-zarna/oron-suuts-zarna/"
PAGES_TO_CHECK = 3          # эхний хэдэн хуудсыг шалгах вэ (VIP зарууд дээгүүр гардаг тул хэдэн хуудас шалгах нь чухал)
REQUEST_DELAY_SEC = 2       # хуудас хооронд түр хүлээх (сайтад дарамт өгөхгүй байх үүднээс)

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "seen_ids.json"
OUTPUT_HTML = Path(__file__).resolve().parent.parent / "docs" / "index.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "mn,en;q=0.9",
}

PRICE_RE = re.compile(r"^[\d.,]+\s*(сая|Тэрбум)\s*₮")
AD_HREF_RE = re.compile(r"^/adv/(\d+)_")


def load_seen() -> set:
    if DATA_FILE.exists():
        try:
            return set(json.loads(DATA_FILE.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            return set()
    return set()


def save_seen(seen_ids: set) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(sorted(seen_ids), ensure_ascii=False, indent=0),
        encoding="utf-8",
    )


def fetch_page(page_num: int) -> str:
    url = BASE_URL if page_num == 1 else f"{BASE_URL}?page={page_num}"
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    return resp.text


def parse_listings(html: str) -> list[dict]:
    """
    unegui.mn-ийн ад блок бүрт нэг URL руу очдог олон <a> tag байдаг
    (зурагнууд бүгд ижил href-тэй, дараа нь үнэ, дараа нь гарчиг).
    Иймд: href-ээр ad_id-г ялгаад, тухайн href-тэй бүх <a>-н текстээс
    үнэ ба гарчгийг таамаглаж авна.
    """
    soup = BeautifulSoup(html, "html.parser")
    order: list[str] = []
    listings: dict[str, dict] = {}

    for a in soup.find_all("a", href=AD_HREF_RE):
        href = a["href"]
        m = AD_HREF_RE.match(href)
        if not m:
            continue
        ad_id = m.group(1)

        if ad_id not in listings:
            listings[ad_id] = {
                "id": ad_id,
                "url": "https://www.unegui.mn" + href,
                "title": None,
                "price": None,
            }
            order.append(ad_id)

        text = a.get_text(strip=True)
        if not text:
            continue

        if PRICE_RE.match(text):
            listings[ad_id]["price"] = text
        else:
            current = listings[ad_id]["title"]
            if current is None or len(text) > len(current):
                listings[ad_id]["title"] = text

    return [listings[i] for i in order]


def build_html_block(new_listings: list[dict]) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"<h2>{now_str} — {len(new_listings)} шинэ зар</h2>", "<ul>"]
    for l in new_listings:
        title = (l["title"] or "(гарчиг олдсонгүй)").replace("<", "&lt;")
        price = (l["price"] or "").replace("<", "&lt;")
        lines.append(
            f'<li><a href="{l["url"]}" target="_blank" rel="noopener">{title}</a> — {price}</li>'
        )
    lines.append("</ul>")
    return "\n".join(lines)


def update_output_html(new_block: str) -> None:
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT_HTML.exists():
        existing = OUTPUT_HTML.read_text(encoding="utf-8")
    else:
        existing = (
            "<!DOCTYPE html>\n<html lang='mn'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Unegui.mn — Шинэ орон сууцны зарууд</title>"
            "<style>body{font-family:sans-serif;max-width:700px;margin:20px auto;padding:0 12px;}"
            "li{margin-bottom:8px;} h2{margin-top:28px;border-top:1px solid #ddd;padding-top:12px;}</style>"
            "</head><body>\n<h1>Unegui.mn — Шинэ орон сууцны зарууд</h1>\n<!--NEW_CONTENT-->\n</body></html>"
        )

    if "<!--NEW_CONTENT-->" in existing:
        existing = existing.replace(
            "<!--NEW_CONTENT-->", new_block + "\n<!--NEW_CONTENT-->"
        )
    else:
        existing = existing.replace("</body>", new_block + "\n</body>")

    OUTPUT_HTML.write_text(existing, encoding="utf-8")


def main() -> None:
    seen = load_seen()
    all_listings: list[dict] = []

    for page in range(1, PAGES_TO_CHECK + 1):
        try:
            html = fetch_page(page)
        except requests.RequestException as e:
            print(f"Хуудас {page}-г татаж чадсангүй: {e}")
            continue
        all_listings.extend(parse_listings(html))
        time.sleep(REQUEST_DELAY_SEC)

    new_listings = [l for l in all_listings if l["id"] not in seen]

    for l in all_listings:
        seen.add(l["id"])
    save_seen(seen)

    block = build_html_block(new_listings)
    update_output_html(block)

    print(f"Нийт шалгасан зар: {len(all_listings)}")
    print(f"Шинэ зар: {len(new_listings)}")


if __name__ == "__main__":
    main()
