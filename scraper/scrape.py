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

UB_DUUREGS = [
    "Багануур", "Багахангай", "Баянгол", "Баянзүрх", "Налайх",
    "Сонгинохайрхан", "Сүхбаатар", "Хан-Уул", "Чингэлтэй",
]
AIMAGS = [
    "Архангай", "Баян-Өлгий", "Баянхонгор", "Булган", "Говь-Алтай",
    "Говьсүмбэр", "Дархан-Уул", "Дорноговь", "Дорнод", "Дундговь",
    "Завхан", "Орхон", "Өвөрхангай", "Өмнөговь", "Сэлэнгэ", "Төв",
    "Увс", "Ховд", "Хөвсгөл", "Хэнтий",
]
# UB дүүргийг эхэнд байрлуулж давуу эрх өгнө (аймаг/дүүргийн ижил нэр давхцахаас сэргийлж)
LOCATION_NAMES = UB_DUUREGS + AIMAGS
LOCATION_RE = re.compile("(" + "|".join(re.escape(n) for n in LOCATION_NAMES) + ")")


def extract_location(a_tag):
    """
    a_tag-аас эхлэн эцэг элементүүд рүү дээш авирч, дүүрэг/аймгийн нэрийг
    агуулсан текст олох хүртэл хайна. Site-ийн яг CSS бүтцээс хамаарахгүй
    байхын тулд ерөнхий (heuristic) аргаар хайна.
    """
    node = a_tag
    for _ in range(4):
        node = node.parent
        if node is None:
            break
        text = node.get_text(" ", strip=True)
        if len(text) > 400:
            # Хэт том container-т хүрсэн тул зогсооно (буруу таарал өгөхөөс сэргийлэх)
            break
        m = LOCATION_RE.search(text)
        if m:
            return m.group(1)
    return None


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
                "location": extract_location(a),
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


def escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_html_block(new_listings: list[dict]) -> str:
    """Нэг өдрийн шинэ зарыг карт хэлбэрийн grid болгож үзүүлнэ."""
    now = datetime.now()
    date_str = now.strftime("%Y.%m.%d")
    time_str = now.strftime("%H:%M")
    count = len(new_listings)

    cards = []
    for l in new_listings:
        title = escape(l["title"] or "(гарчиг олдсонгүй)")
        price = escape(l["price"] or "—")
        location = l.get("location") or "Бусад"
        loc_attr = escape(location)
        cards.append(
            f'''      <a class="card" href="{l["url"]}" target="_blank" rel="noopener" data-location="{loc_attr}">
        <span class="card__title">{title}</span>
        <span class="card__row">
          <span class="card__price">{price}</span>
          <span class="card__loc">{escape(location)}</span>
        </span>
      </a>'''
        )

    if cards:
        grid = '<div class="grid">\n' + "\n".join(cards) + "\n      </div>"
    else:
        grid = '<p class="empty">Энэ удаад шинэ зар олдсонгүй.</p>'

    return f'''    <section class="day">
      <div class="day__label">
        <span class="day__date">{date_str}</span>
        <span class="day__count">{count} шинэ зар · {time_str}</span>
      </div>
{grid}
    </section>'''


PAGE_SHELL = """<!DOCTYPE html>
<html lang="mn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Шинэ байр — Unegui.mn хянагч</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Unbounded:wght@500;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<style>
  :root{
    --navy:#081C2D;
    --navy-deep:#04101A;
    --emerald:#1F7A63;
    --emerald-tint:#E3F1EC;
    --white:#F5F7FA;
    --gray:#9AA3A8;
  }
  *{box-sizing:border-box;}
  body{
    margin:0;
    background:var(--white);
    color:var(--navy);
    font-family:'Inter',sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  a{color:inherit;text-decoration:none;}

  header{
    position:sticky;top:0;z-index:10;
    background:linear-gradient(160deg,var(--navy) 60%,var(--navy-deep));
    color:var(--white);
    padding:22px 20px 18px;
    overflow:hidden;
  }
  .skyline{
    position:absolute;inset:0;
    opacity:.9;pointer-events:none;
  }
  header .inner{position:relative;}
  .eyebrow{
    font-family:'IBM Plex Mono',monospace;
    font-size:11px;letter-spacing:.14em;text-transform:uppercase;
    color:var(--emerald);opacity:.95;
    margin:0 0 6px;
  }
  h1{
    font-family:'Unbounded',sans-serif;
    font-weight:700;
    font-size:clamp(22px,6vw,28px);
    margin:0 0 6px;
    letter-spacing:-0.01em;
  }
  .meta{
    font-family:'IBM Plex Mono',monospace;
    font-size:12px;color:var(--gray);
    margin:0;
  }

  main{max-width:720px;margin:0 auto;padding:18px 16px 60px;}

  .day{margin-top:26px;}
  .day:first-of-type{margin-top:20px;}
  .day__label{
    display:flex;align-items:baseline;justify-content:space-between;
    border-bottom:2px solid var(--navy);
    padding-bottom:8px;margin-bottom:14px;
  }
  .day__date{
    font-family:'Unbounded',sans-serif;
    font-weight:600;font-size:16px;color:var(--navy);
  }
  .day__count{
    font-family:'IBM Plex Mono',monospace;
    font-size:12px;color:var(--emerald);
  }

  .grid{display:grid;grid-template-columns:1fr;gap:10px;}
  @media (min-width:560px){.grid{grid-template-columns:1fr 1fr;}}

  .card{
    display:flex;flex-direction:column;gap:8px;
    background:#fff;
    border:1px solid #E4E7EA;
    border-left:3px solid var(--emerald);
    border-radius:10px;
    padding:13px 14px;
    transition:transform .12s ease, box-shadow .12s ease;
  }
  .card:active{transform:scale(.98);}
  @media (hover:hover){
    .card:hover{box-shadow:0 4px 14px rgba(8,28,45,.08);transform:translateY(-1px);}
  }
  .card__title{
    font-size:14.5px;font-weight:500;line-height:1.35;color:var(--navy);
  }
  .card__row{
    display:flex;align-items:center;justify-content:space-between;gap:8px;
  }
  .card__price{
    font-family:'IBM Plex Mono',monospace;
    font-size:12.5px;font-weight:500;
    color:var(--emerald);
    background:var(--emerald-tint);
    padding:3px 8px;border-radius:6px;
  }
  .card__loc{
    font-family:'IBM Plex Mono',monospace;
    font-size:11px;color:var(--gray);
    white-space:nowrap;
  }

  .empty{
    font-family:'IBM Plex Mono',monospace;
    font-size:13px;color:var(--gray);
    padding:10px 0;
  }

  .filterbar{
    position:relative;margin-top:16px;
    display:flex;align-items:center;gap:8px;
  }
  .filterbar select{
    appearance:none;-webkit-appearance:none;
    font-family:'IBM Plex Mono',monospace;
    font-size:12.5px;color:var(--navy);
    background:var(--white) url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6"><path d="M0 0L5 6L10 0Z" fill="%23081C2D"/></svg>') no-repeat right 12px center;
    border:1px solid #D8DCDF;border-radius:8px;
    padding:9px 30px 9px 12px;
    width:100%;
  }

  footer{
    max-width:720px;margin:0 auto;padding:0 16px 30px;
    font-family:'IBM Plex Mono',monospace;
    font-size:11px;color:var(--gray);text-align:center;
  }
</style>
</head>
<body>
<header>
  <svg class="skyline" viewBox="0 0 400 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="14" y="34" width="26" height="56" fill="#0E3D30"/>
    <rect x="46" y="18" width="22" height="72" fill="#134A3A"/>
    <rect x="74" y="42" width="20" height="48" fill="#0E3D30"/>
    <rect x="100" y="8"  width="30" height="82" fill="#1F7A63"/>
    <rect x="136" y="28" width="18" height="62" fill="#134A3A"/>
    <rect x="160" y="46" width="24" height="44" fill="#0E3D30"/>
    <rect x="190" y="14" width="22" height="76" fill="#1F7A63"/>
    <rect x="218" y="36" width="18" height="54" fill="#134A3A"/>
    <rect x="242" y="22" width="26" height="68" fill="#0E3D30"/>
    <rect x="274" y="44" width="20" height="46" fill="#134A3A"/>
    <rect x="300" y="10" width="28" height="80" fill="#1F7A63"/>
    <rect x="334" y="32" width="20" height="58" fill="#0E3D30"/>
    <rect x="360" y="48" width="26" height="42" fill="#134A3A"/>
    <g fill="#F5F7FA" opacity=".55">
      <rect x="19" y="42" width="3" height="3"/><rect x="28" y="52" width="3" height="3"/><rect x="19" y="62" width="3" height="3"/>
      <rect x="53" y="28" width="3" height="3"/><rect x="61" y="42" width="3" height="3"/><rect x="53" y="58" width="3" height="3"/>
      <rect x="107" y="18" width="3" height="3"/><rect x="118" y="30" width="3" height="3"/><rect x="107" y="44" width="3" height="3"/><rect x="118" y="58" width="3" height="3"/>
      <rect x="197" y="24" width="3" height="3"/><rect x="205" y="38" width="3" height="3"/><rect x="197" y="52" width="3" height="3"/><rect x="205" y="66" width="3" height="3"/>
      <rect x="249" y="32" width="3" height="3"/><rect x="259" y="46" width="3" height="3"/><rect x="249" y="60" width="3" height="3"/>
      <rect x="307" y="20" width="3" height="3"/><rect x="317" y="34" width="3" height="3"/><rect x="307" y="48" width="3" height="3"/><rect x="317" y="62" width="3" height="3"/>
    </g>
  </svg>
  <div class="inner">
    <p class="eyebrow">unegui.mn · орон сууц зарна</p>
    <h1>Шинэ байр</h1>
    <p class="meta">Өдөр бүр автоматаар шалгаж, шинэ зарыг доор нэмнэ</p>
    <div class="filterbar">
      <select id="locationFilter" onchange="filterByLocation(this.value)">
        <option value="">Бүх дүүрэг / аймаг</option>
        <optgroup label="Улаанбаатар">
          <option>Багануур</option><option>Багахангай</option><option>Баянгол</option>
          <option>Баянзүрх</option><option>Налайх</option><option>Сонгинохайрхан</option>
          <option>Сүхбаатар</option><option>Хан-Уул</option><option>Чингэлтэй</option>
        </optgroup>
        <optgroup label="Аймаг">
          <option>Архангай</option><option>Баян-Өлгий</option><option>Баянхонгор</option>
          <option>Булган</option><option>Говь-Алтай</option><option>Говьсүмбэр</option>
          <option>Дархан-Уул</option><option>Дорноговь</option><option>Дорнод</option>
          <option>Дундговь</option><option>Завхан</option><option>Орхон</option>
          <option>Өвөрхангай</option><option>Өмнөговь</option><option>Сэлэнгэ</option>
          <option>Төв</option><option>Увс</option><option>Ховд</option>
          <option>Хөвсгөл</option><option>Хэнтий</option>
        </optgroup>
        <option value="Бусад">Байршил тодорхойгүй</option>
      </select>
    </div>
  </div>
</header>
<main>
<!--NEW_CONTENT-->
</main>
<footer>Хувийн хэрэглээнд зориулсан автомат хянагч</footer>
<script>
function filterByLocation(loc){
  document.querySelectorAll('.card').forEach(function(card){
    var match = !loc || card.getAttribute('data-location') === loc;
    card.style.display = match ? '' : 'none';
  });
  document.querySelectorAll('.day').forEach(function(day){
    var visible = day.querySelectorAll('.card').length === 0 ||
      Array.prototype.some.call(day.querySelectorAll('.card'), function(c){return c.style.display !== 'none';});
    day.style.display = visible ? '' : 'none';
  });
}
</script>
</body>
</html>"""


def update_output_html(new_block: str) -> None:
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT_HTML.exists():
        existing = OUTPUT_HTML.read_text(encoding="utf-8")
    else:
        existing = PAGE_SHELL

    if "<!--NEW_CONTENT-->" in existing:
        existing = existing.replace(
            "<!--NEW_CONTENT-->", new_block + "\n<!--NEW_CONTENT-->"
        )
    else:
        existing = existing.replace("</main>", new_block + "\n</main>")

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
