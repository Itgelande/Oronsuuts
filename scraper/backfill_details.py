"""
Нэг удаагийн скрипт: docs/index.html дотор аль хэдийн байгаа боловч
дэлгэрэнгүй мэдээлэл (утас, талбай, өрөө, давхар, нарийвчилсан байршил)
дутуу картуудыг олж, тэдгээрийн зарын дэлгэрэнгүй хуудаснаас мэдээллийг
татаж бөглөнө.

Зөвхөн GitHub Actions-ийн workflow_dispatch-аар л ажиллуулна (гараар нэг
удаа эхлүүлнэ), учир нь энэ орчинд л unegui.mn руу шууд сүлжээ хандалт бий.
"""

import re
import time
from pathlib import Path

from scrape import (
    escape,
    fetch_detail,
    format_phone,
    load_seen,
    price_bucket,
    price_per_sqm,
    save_seen,
)

OUTPUT_HTML = Path(__file__).resolve().parent.parent / "docs" / "index.html"
REQUEST_DELAY_SEC = 2
MAX_BACKFILL = 400  # аюулгүйн хязгаар

CARD_RE = re.compile(
    r'<div class="card" data-location="(?P<loc>[^"]*)" data-rooms="(?P<rooms>[^"]*)" '
    r'data-price="(?P<pricebucket>[^"]*)"(?: data-published="(?P<pub>[^"]*)")?>\s*'
    r'<a class="card__go"[^>]*>.*?</a>\s*'
    r'<a class="card__title" href="(?P<url>[^"]+)"[^>]*>(?P<title>[^<]*)</a>\s*'
    r'(?:<span class="card__specs">(?P<specs>[^<]*)</span>\s*)?'
    r'<div class="card__row">\s*'
    r'<span class="card__price">(?P<price>[^<]*)</span>\s*'
    r'<span class="card__loc">[^<]*</span>\s*'
    r'</div>\s*'
    r'(?:<a class="card__phone" href="tel:(?P<phone>[^"]*)">[^<]*</a>|'
    r'<span class="card__phone[^"]*">[^<]*</span>)\s*'
    r'</div>',
    re.DOTALL,
)


def build_card(url: str, title: str, price: str, location: str, rooms: str, details: dict) -> str:
    loc = details.get("location") or location or "Бусад"
    rooms_val = details.get("rooms") or (rooms if rooms and rooms != "5+" else None)
    try:
        rooms_num = int(rooms_val) if rooms_val else None
    except ValueError:
        rooms_num = None
    rooms_attr = ("5+" if rooms_num and rooms_num >= 5 else str(rooms_num)) if rooms_num else ""

    spec_parts = []
    if details.get("area"):
        spec_parts.append(escape(details["area"]))
    if rooms_val:
        spec_parts.append(f"{escape(str(rooms_val))} өрөө")
    if details.get("floor") and details.get("total_floors"):
        spec_parts.append(f'{escape(details["floor"])}/{escape(details["total_floors"])} давхар')
    elif details.get("total_floors"):
        spec_parts.append(f'{escape(details["total_floors"])} давхартай')
    pps = price_per_sqm(price, details.get("area") or "")
    if pps:
        spec_parts.append(escape(pps))
    if details.get("published"):
        pub_date = details["published"].split(" ")[0]
        spec_parts.append(f"🗓 {escape(pub_date)}")
    specs_html = (
        f'<span class="card__specs">{" · ".join(spec_parts)}</span>' if spec_parts else ""
    )

    phone = details.get("phone")
    if phone:
        phone_html = (
            f'<a class="card__phone" href="tel:{escape(phone)}">'
            f"📞 {escape(format_phone(phone))}</a>"
        )
    else:
        phone_html = '<span class="card__phone card__phone--missing">Утас олдсонгүй</span>'

    price_attr = price_bucket(price)
    pub_attr = escape(details["published"].split(" ")[0]) if details.get("published") else ""
    link_icon = (
        f'<a class="card__go" href="{url}" target="_blank" rel="noopener" aria-label="Зарыг үзэх">'
        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M7 17L17 7M9 7h8v8"/></svg></a>'
    )

    return (
        f'<div class="card" data-location="{escape(loc)}" data-rooms="{rooms_attr}" '
        f'data-price="{price_attr}" data-published="{pub_attr}">\n'
        f"        {link_icon}\n"
        f'        <a class="card__title" href="{url}" target="_blank" rel="noopener">{escape(title)}</a>\n'
        f"        {specs_html}\n"
        f'        <div class="card__row">\n'
        f'          <span class="card__price">{escape(price)}</span>\n'
        f'          <span class="card__loc">{escape(loc)}</span>\n'
        f"        </div>\n"
        f"        {phone_html}\n"
        f"      </div>"
    )


import re as _re

AD_ID_RE = _re.compile(r"/adv/(\d+)_")


SPEC_AREA_RE = re.compile(r"([\d.]+\s*м²)")
SPEC_FLOOR_RE = re.compile(r"(\d+)/(\d+)\s*давхар(?!тай)")
SPEC_TOTAL_FLOORS_RE = re.compile(r"(\d+)\s*давхартай")


def parse_existing_specs(specs_text: str | None) -> dict:
    """Картан дээр аль хэдийн байгаа specs текстээс талбай/давхрын мэдээллийг сэргээнэ."""
    existing: dict = {}
    if not specs_text:
        return existing
    area_m = SPEC_AREA_RE.search(specs_text)
    if area_m:
        existing["area"] = area_m.group(1)
    floor_m = SPEC_FLOOR_RE.search(specs_text)
    if floor_m:
        existing["floor"], existing["total_floors"] = floor_m.group(1), floor_m.group(2)
    else:
        tf_m = SPEC_TOTAL_FLOORS_RE.search(specs_text)
        if tf_m:
            existing["total_floors"] = tf_m.group(1)
    return existing


def main() -> None:
    html = OUTPUT_HTML.read_text(encoding="utf-8")
    seen = load_seen()

    matches = list(CARD_RE.finditer(html))
    print(f"Нийт олдсон карт: {len(matches)}")

    # Одоо зорилго: нийтлэгдсэн огноо дутуу картыг олж, дэлгэрэнгүй хуудаснаас нь татна
    todo = [m for m in matches if not (m.group("pub") or "").strip()]
    print(f"Огноогүй карт (татах ёстой): {len(todo)}")

    updated_html = html
    offset = 0
    success = 0
    failed = 0

    for i, m in enumerate(todo[:MAX_BACKFILL]):
        url = m.group("url")
        print(f"[{i + 1}/{min(len(todo), MAX_BACKFILL)}] {url}")

        # Одоо байгаа (алдахгүй хадгалах) мэдээллийг эхлээд бэлдэнэ
        prev_details = parse_existing_specs(m.group("specs"))
        if m.group("phone"):
            prev_details["phone"] = m.group("phone")

        try:
            fresh = fetch_detail(url)
        except Exception as e:  # noqa: BLE001
            print(f"  Алдаа: {e}")
            fresh = {}
            failed += 1
        else:
            if fresh.get("published"):
                success += 1

        # Шинээр амжилттай татсан талбарууд хуучныг дарж бичнэ; амжилтгүй
        # бол хуучин (аль хэдийн байсан) утга хэвээрээ үлдэнэ
        details = {**prev_details, **fresh}

        id_m = AD_ID_RE.search(url)
        if id_m and details.get("published"):
            seen[id_m.group(1)] = details["published"]

        new_card = build_card(
            url=url,
            title=m.group("title"),
            price=m.group("price"),
            location=m.group("loc"),
            rooms=m.group("rooms"),
            details=details,
        )

        start = m.start() + offset
        end = m.end() + offset
        updated_html = updated_html[:start] + new_card + updated_html[end:]
        offset += len(new_card) - (m.end() - m.start())

        time.sleep(REQUEST_DELAY_SEC)

    OUTPUT_HTML.write_text(updated_html, encoding="utf-8")
    save_seen(seen)
    print(f"Огноо олдсон: {success}, амжилтгүй: {failed}")
    print("docs/index.html болон data/seen_ids.json шинэчлэгдлээ")


if __name__ == "__main__":
    main()
