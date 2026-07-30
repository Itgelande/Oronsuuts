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
MAX_PAGES = 20              # хамгийн ихдээ хэдэн хуудас шалгах вэ (аюулгүйн хязгаар)
REQUEST_DELAY_SEC = 2       # хуудас/зар хооронд түр хүлээх (сайтад дарамт өгөхгүй байх үүднээс)

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

PRICE_SPLIT_RE = re.compile(r"[\d.,]+\s*(?:сая|Тэрбум)\s*₮")


def clean_price(text: str) -> str:
    """
    Хямдралтай зарууд заримдаа хуучин ба шинэ үнийг зайгүй наалдуулж
    харуулдаг (жишээ нь "139 сая₮145 сая₮"). Ийм тохиолдолд СҮҮЛИЙН
    (одоогийн, хямдруулсан) үнийг л авна.
    """
    matches = PRICE_SPLIT_RE.findall(text)
    if len(matches) > 1:
        return matches[-1]
    return text

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


def load_seen() -> dict:
    """
    seen_ids.json-г уншина. Хуучин форматтай (зөвхөн ID-н жагсаалт) файл
    байвал шинэ формат (ID -> нийтлэгдсэн огноо) руу автоматаар хөрвүүлнэ.
    """
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if isinstance(data, list):
            return {ad_id: None for ad_id in data}
        if isinstance(data, dict):
            return data
    return {}


def save_seen(seen: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(seen, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8",
    )


def fetch_page(page_num: int) -> str:
    url = BASE_URL if page_num == 1 else f"{BASE_URL}?page={page_num}"
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    return resp.text


TEL_RE = re.compile(r'href="tel:(\+?\d+)"')
AREA_RE = re.compile(r"Талбай[:\s]+([\d.,]+)\s*м")
FLOOR_RE = re.compile(r"Хэдэн давхарт[:\s]+(\d+)")
TOTAL_FLOORS_RE = re.compile(r"Барилгын давхар[:\s]+(\d+)")
FULL_LOCATION_RE = re.compile(r"Байршил[:\s]+([^\n]+)")
ROOMS_RE = re.compile(r"(\d+)\s*өрөө")
PUBLISHED_RE = re.compile(r"Нийтэлсэн:\s*([\d]{4}-[\d]{2}-[\d]{2}\s+[\d]{2}:[\d]{2})")


def fetch_detail(url: str) -> dict:
    """
    Зарын дэлгэрэнгүй хуудаснаас: утасны дугаар, талбай, давхар,
    нийт давхрын тоо, өрөөний тоо, нарийвчилсан байршлыг татна.
    """
    details: dict = {}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Дэлгэрэнгүй хуудас татагдсангүй ({url}): {e}")
        return details

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    tel_m = TEL_RE.search(html)
    if tel_m:
        details["phone"] = tel_m.group(1)

    area_m = AREA_RE.search(text)
    if area_m:
        details["area"] = area_m.group(1).replace(",", ".") + " м²"

    floor_m = FLOOR_RE.search(text)
    if floor_m:
        details["floor"] = floor_m.group(1)

    total_floors_m = TOTAL_FLOORS_RE.search(text)
    if total_floors_m:
        details["total_floors"] = total_floors_m.group(1)

    published_m = PUBLISHED_RE.search(text)
    if published_m:
        details["published"] = published_m.group(1)

    loc_m = FULL_LOCATION_RE.search(text)
    if loc_m:
        full_loc = loc_m.group(1).strip()
        details["full_location"] = full_loc
        district_m = LOCATION_RE.search(full_loc)
        if district_m:
            details["location"] = district_m.group(1)

    rooms_m = ROOMS_RE.search(text)
    if rooms_m:
        details["rooms"] = rooms_m.group(1)

    return details


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
            listings[ad_id]["price"] = clean_price(text)
        else:
            current = listings[ad_id]["title"]
            if current is None or len(text) > len(current):
                listings[ad_id]["title"] = text

    return [listings[i] for i in order]


def escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_phone(phone: str) -> str:
    """+97688112233 -> 8811-2233 хэлбэрт харуулна (сүүлийн 8 оронг)."""
    digits = re.sub(r"\D", "", phone)
    digits = digits[-8:] if len(digits) >= 8 else digits
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:]}"
    return digits


PRICE_BUCKET_RE = re.compile(r"([\d.,]+)\s*(сая|Тэрбум)")


def price_bucket(price_str: str) -> str:
    """
    Үнийг сая ₮-ээр тооцож, доорх бүлгүүдийн аль нэгэнд оноож өгнө:
    0-200 / 200-300 / 300-400 / 400-500 / 500-1000 / 1000+
    (1000 сая = 1 тэрбум). Хэрэв текст дотор хэд хэдэн үнэ агуулагдвал
    СҮҮЛИЙН (одоогийн) үнийг ашиглана. Тоо ялгаж чадахгүй бол хоосон буцаана.
    """
    if not price_str:
        return ""
    matches = PRICE_BUCKET_RE.findall(price_str)
    if not matches:
        return ""
    num_str, unit = matches[-1]
    try:
        num = float(num_str.replace(",", "."))
    except ValueError:
        return ""
    million = num * 1000 if unit == "Тэрбум" else num

    if million <= 200:
        return "0-200"
    if million <= 300:
        return "200-300"
    if million <= 400:
        return "300-400"
    if million <= 500:
        return "400-500"
    if million <= 1000:
        return "500-1000"
    return "1000+"


AREA_NUM_RE = re.compile(r"([\d.,]+)")


def price_per_sqm(price_str: str, area_str: str) -> str:
    """
    Нийт үнэ ба талбайгаас 1 м²-ийн үнийг тооцоолж, "X.XX сая/м²" эсвэл
    том дүн бол "X сая/м²" хэлбэрээр буцаана. Тооцох боломжгүй бол хоосон.
    """
    if not price_str or not area_str:
        return ""
    price_matches = PRICE_BUCKET_RE.findall(price_str)
    if not price_matches:
        return ""
    num_str, unit = price_matches[-1]
    try:
        total_million = float(num_str.replace(",", ".")) * (1000 if unit == "Тэрбум" else 1)
    except ValueError:
        return ""

    area_m = AREA_NUM_RE.search(area_str)
    if not area_m:
        return ""
    try:
        area_val = float(area_m.group(1).replace(",", "."))
    except ValueError:
        return ""
    if area_val <= 0:
        return ""

    per_sqm = total_million / area_val
    return f"{per_sqm:.2f} сая/м²"


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

        rooms_val = l.get("rooms")
        try:
            rooms_num = int(rooms_val) if rooms_val else None
        except ValueError:
            rooms_num = None
        rooms_attr = ("5+" if rooms_num and rooms_num >= 5 else str(rooms_num)) if rooms_num else ""

        spec_parts = []
        if l.get("area"):
            spec_parts.append(escape(l["area"]))
        if l.get("rooms"):
            spec_parts.append(f'{escape(l["rooms"])} өрөө')
        if l.get("floor") and l.get("total_floors"):
            spec_parts.append(f'{escape(l["floor"])}/{escape(l["total_floors"])} давхар')
        elif l.get("total_floors"):
            spec_parts.append(f'{escape(l["total_floors"])} давхартай')
        pps = price_per_sqm(l.get("price") or "", l.get("area") or "")
        if pps:
            spec_parts.append(escape(pps))
        if l.get("published"):
            pub_date = l["published"].split(" ")[0]  # зөвхөн огноог нь авна (цагийг нь хасна)
            spec_parts.append(f"🗓 {escape(pub_date)}")
        specs_html = (
            f'<span class="card__specs">{" · ".join(spec_parts)}</span>'
            if spec_parts else ""
        )

        phone = l.get("phone")
        if phone:
            phone_html = (
                f'<a class="card__phone" href="tel:{escape(phone)}">'
                f'📞 {escape(format_phone(phone))}</a>'
            )
        else:
            phone_html = '<span class="card__phone card__phone--missing">Утас олдсонгүй</span>'

        price_attr = price_bucket(l.get("price") or "")

        link_icon = (
            f'<a class="card__go" href="{l["url"]}" target="_blank" rel="noopener" aria-label="Зарыг үзэх">'
            '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M7 17L17 7M9 7h8v8"/></svg></a>'
        )

        pub_attr = escape(l["published"].split(" ")[0]) if l.get("published") else ""

        cards.append(
            f'''      <div class="card" data-location="{loc_attr}" data-rooms="{rooms_attr}" data-price="{price_attr}" data-published="{pub_attr}">
        {link_icon}
        <a class="card__title" href="{l["url"]}" target="_blank" rel="noopener">{title}</a>
        {specs_html}
        <div class="card__row">
          <span class="card__price">{price}</span>
          <span class="card__loc">{escape(location)}</span>
        </div>
        {phone_html}
      </div>'''
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
    position:relative;
    display:flex;flex-direction:column;gap:7px;
    background:#fff;
    border:1px solid #E4E7EA;
    border-left:3px solid var(--emerald);
    border-radius:10px;
    padding:13px 44px 13px 14px;
    transition:transform .12s ease, box-shadow .12s ease;
  }
  .card:active{transform:scale(.98);}
  @media (hover:hover){
    .card:hover{box-shadow:0 4px 14px rgba(8,28,45,.08);transform:translateY(-1px);}
  }
  .card__go{
    position:absolute;top:11px;right:11px;
    width:30px;height:30px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;
    background:var(--emerald);color:#fff;
    box-shadow:0 2px 6px rgba(31,122,99,.35);
    transition:transform .15s ease, background .15s ease;
  }
  .card__go:active{transform:scale(.88);}
  @media (hover:hover){
    .card__go:hover{background:var(--navy);transform:scale(1.1);}
  }
  .card__title{
    display:block;
    padding-right:4px;
    font-size:14.5px;font-weight:500;line-height:1.35;color:var(--navy);
  }
  .card__specs{
    font-family:'IBM Plex Mono',monospace;
    font-size:11.5px;color:var(--navy);opacity:.65;
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
  .card__phone{
    display:inline-flex;align-items:center;gap:5px;
    font-family:'IBM Plex Mono',monospace;
    font-size:12px;font-weight:500;
    color:var(--navy);
    background:var(--white);
    border:1px solid #E4E7EA;
    border-radius:6px;
    padding:5px 9px;
    width:fit-content;
    margin-top:2px;
  }
  .card__phone--missing{
    color:var(--gray);font-weight:400;border-style:dashed;
  }

  .empty{
    font-family:'IBM Plex Mono',monospace;
    font-size:13px;color:var(--gray);
    padding:10px 0;
  }

  .filterbar{
    position:relative;margin-top:16px;
    display:flex;flex-wrap:wrap;align-items:center;gap:8px;
  }
  .filterbar select{
    appearance:none;-webkit-appearance:none;
    font-family:'IBM Plex Mono',monospace;
    font-size:12.5px;color:var(--navy);
    background:var(--white) url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6"><path d="M0 0L5 6L10 0Z" fill="%23081C2D"/></svg>') no-repeat right 12px center;
    border:1px solid #D8DCDF;border-radius:8px;
    padding:9px 30px 9px 12px;
    flex:1 1 140px;
    min-width:0;
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
      <select id="locationFilter" onchange="filterListings()">
        <option value="">Бүх дүүрэг</option>
        <option>Багануур</option><option>Багахангай</option><option>Баянгол</option>
        <option>Баянзүрх</option><option>Налайх</option><option>Сонгинохайрхан</option>
        <option>Сүхбаатар</option><option>Хан-Уул</option><option>Чингэлтэй</option>
        <option value="Бусад">Байршил тодорхойгүй</option>
      </select>
      <select id="roomsFilter" onchange="filterListings()">
        <option value="">Бүх өрөө</option>
        <option value="1">1 өрөө</option>
        <option value="2">2 өрөө</option>
        <option value="3">3 өрөө</option>
        <option value="4">4 өрөө</option>
        <option value="5+">5+ өрөө</option>
      </select>
      <select id="priceFilter" onchange="filterListings()">
        <option value="">Бүх үнэ</option>
        <option value="0-200">200 сая хүртэл</option>
        <option value="200-300">200-300 сая</option>
        <option value="300-400">300-400 сая</option>
        <option value="400-500">400-500 сая</option>
        <option value="500-1000">500 сая - 1 тэрбум</option>
        <option value="1000+">1 тэрбумаас дээш</option>
      </select>
      <select id="dateFilter" onchange="filterListings()">
        <option value="">Бүх огноо</option>
        <option value="today">Өнөөдөр</option>
        <option value="7d">Сүүлийн 7 хоног</option>
        <option value="14d">Сүүлийн 14 хоног</option>
        <option value="1m">Сүүлийн 1 сар</option>
        <option value="3m">Сүүлийн 3 сар</option>
        <option value="3m+">3 сараас дээш</option>
      </select>
    </div>
  </div>
</header>
<main>
<!--NEW_CONTENT-->
</main>
<footer>Хувийн хэрэглээнд зориулсан автомат хянагч</footer>
<script>
function daysAgo(dateStr){
  if(!dateStr) return null;
  var pub = new Date(dateStr + 'T00:00:00');
  if(isNaN(pub.getTime())) return null;
  var now = new Date();
  now.setHours(0,0,0,0);
  return Math.round((now - pub) / 86400000);
}
function dateBucket(days){
  if(days === null) return '';
  if(days <= 0) return 'today';
  if(days <= 7) return '7d';
  if(days <= 14) return '14d';
  if(days <= 30) return '1m';
  if(days <= 90) return '3m';
  return '3m+';
}
function filterListings(){
  var loc = document.getElementById('locationFilter').value;
  var rooms = document.getElementById('roomsFilter').value;
  var price = document.getElementById('priceFilter').value;
  var dateSel = document.getElementById('dateFilter').value;
  document.querySelectorAll('.card').forEach(function(card){
    var locMatch = !loc || card.getAttribute('data-location') === loc;
    var roomsMatch = !rooms || card.getAttribute('data-rooms') === rooms;
    var priceMatch = !price || card.getAttribute('data-price') === price;
    var dateMatch = !dateSel || dateBucket(daysAgo(card.getAttribute('data-published'))) === dateSel;
    card.style.display = (locMatch && roomsMatch && priceMatch && dateMatch) ? '' : 'none';
  });
  document.querySelectorAll('.day').forEach(function(day){
    var cards = day.querySelectorAll('.card');
    var visible = cards.length === 0 ||
      Array.prototype.some.call(cards, function(c){return c.style.display !== 'none';});
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


MAX_DETAIL_FETCHES = 300  # нэг ажиллагаанд дэлгэрэнгүй хуудас хэдэн зарын татах дээд хязгаар


def main() -> None:
    seen = load_seen()
    all_listings: list[dict] = []
    new_listings: list[dict] = []

    # Сүүлд хадгалсан зараас хойш орсон бүх зарыг олох хүртэл хуудсаар үргэлжлүүлж татна.
    # Хуудас бүрд шинэ зар олдохгүй болмогц зогсооно (MAX_PAGES хүртэл аюулгүйн хязгаартай).
    for page in range(1, MAX_PAGES + 1):
        try:
            html = fetch_page(page)
        except requests.RequestException as e:
            print(f"Хуудас {page}-г татаж чадсангүй: {e}")
            break

        page_listings = parse_listings(html)
        all_listings.extend(page_listings)

        page_new = [l for l in page_listings if l["id"] not in seen]
        new_listings.extend(page_new)

        print(f"Хуудас {page}: {len(page_listings)} зар, {len(page_new)} шинэ")
        time.sleep(REQUEST_DELAY_SEC)

        if not page_new and page > 1:
            # Энэ хуудсанд шинэ зар олдоогүй тул цаашид ч байхгүй гэж үзнэ
            break

    # Улаанбаатар биш (аймгийн) зарыг эрт шүүж хасна — дэлгэрэнгүй хуудсыг ч
    # дэмий татахгүй байх зорилготой. location тодорхойгүй (None) зар цаашид
    # дэлгэрэнгүй хуудаснаас дахин шалгагдана.
    ub_candidates = [l for l in new_listings if l.get("location") not in AIMAGS]
    skipped_aimag = len(new_listings) - len(ub_candidates)

    # Зөвхөн Улаанбаатар байж болзошгүй шинэ зарын дэлгэрэнгүй мэдээллийг
    # (утас, талбай, давхар, өрөө, нарийвчилсан байршил) татна
    for l in ub_candidates[:MAX_DETAIL_FETCHES]:
        details = fetch_detail(l["url"])
        l.update(details)
        time.sleep(REQUEST_DELAY_SEC)

    # Дэлгэрэнгүй хуудаснаас олсон нарийвчилсан байршлаар дахин шалгаж,
    # бодитоор аймагт байгаа нь илэрвэл эцсийн жагсаалтаас хасна
    display_listings = [l for l in ub_candidates if l.get("location") not in AIMAGS]
    skipped_aimag += len(ub_candidates) - len(display_listings)

    for l in all_listings:
        if l["id"] not in seen:
            seen[l["id"]] = None

    # Дэлгэрэнгүй хуудаснаас олдсон нийтлэгдсэн бодит огноог seen сан руу бичнэ
    for l in ub_candidates[:MAX_DETAIL_FETCHES]:
        if l.get("published"):
            seen[l["id"]] = l["published"]

    save_seen(seen)

    block = build_html_block(display_listings)
    update_output_html(block)

    print(f"Нийт шалгасан зар: {len(all_listings)}")
    print(f"Шинэ зар (нийт): {len(new_listings)}")
    print(f"Аймгийн зар учир хасагдсан: {skipped_aimag}")
    print(f"Улаанбаатарын шинэ зар (харуулсан): {len(display_listings)}")


if __name__ == "__main__":
    main()
