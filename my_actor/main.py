from __future__ import annotations

from urllib.parse import urlparse, parse_qs

from apify import Actor
from httpx2 import AsyncClient

DEFAULT_SHOP_URL = "https://shopee.co.id/waterlilyliterary"
SHOP_DOMAIN = "https://shopee.co.id"
CURRENCY = "IDR"


def parse_shop_username(shop_url: str) -> str:
    """Ambil username dari URL toko Shopee."""
    parsed = urlparse(shop_url)
    username = parsed.path.strip("/").split("/")[0]

    if not username:
        raise ValueError(f"URL toko tidak valid: {shop_url}")

    return username


def parse_products(payload: dict) -> list:
    """Ambil daftar produk dari beberapa format respons Shopee."""
    data = payload.get("data")

    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items

        # Beberapa endpoint mengembalikan produk di dalam sections.
        products = []
        for section in data.get("sections", []) or []:
            if not isinstance(section, dict):
                continue

            section_data = section.get("data") or {}
            section_items = section_data.get("item") or []
            if isinstance(section_items, list):
                products.extend(section_items)

        return products

    items = payload.get("items")
    return items if isinstance(items, list) else []


def normalize_product(item: dict, keyword: str, shop_url: str) -> dict | None:
    """Normalisasi satu produk menjadi record dataset."""
    if not isinstance(item, dict):
        return None

    # Respons endpoint toko bisa membungkus data item.
    if isinstance(item.get("item_basic"), dict):
        item = item["item_basic"]

    name = item.get("name")
    if not name:
        return None

    # Filter keyword berdasarkan nama produk.
    if keyword and keyword not in str(name).lower():
        return None

    shop_id = item.get("shopid")
    item_id = item.get("itemid")

    raw_price = item.get("price_min")
    if raw_price is None:
        raw_price = item.get("price")

    raw_price_max = item.get("price_max")
    if raw_price_max is None:
        raw_price_max = raw_price

    def convert_price(value):
        if value is None:
            return None
        try:
            return int(value) / 100000
        except (TypeError, ValueError):
            return None

    rating = item.get("item_rating") or {}
    if not isinstance(rating, dict):
        rating = {}

    product_url = None
    if shop_id and item_id:
        product_url = (
            f"{SHOP_DOMAIN}/product/{shop_id}/{item_id}"
        )

    image_id = item.get("image")
    image_url = (
        f"https://down-id.img.susercontent.com/file/{image_id}"
        if image_id
        else None
    )

    return {
        "keyword": keyword or "(semua produk)",
        "product_name": name,
        "price_min": convert_price(raw_price),
        "price_max": convert_price(raw_price_max),
        "currency": CURRENCY,
        "shop_name": item.get("shop_name"),
        "shop_id": shop_id,
        "item_id": item_id,
        "rating": rating.get("rating_star"),
        "rating_count": item.get("cmt_count"),
        "sold": item.get("historical_sold", item.get("sold")),
        "product_url": product_url,
        "image_url": image_url,
        "shop_url": shop_url,
    }


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}

        shop_url = str(
            actor_input.get("shopUrl") or DEFAULT_SHOP_URL
        ).strip()

        keywords = actor_input.get("keywords", [])
        max_items = int(actor_input.get("maxItems", 40))

        if isinstance(keywords, str):
            keywords = [keywords]

        keywords = [
            str(keyword).strip().lower()
            for keyword in keywords
            if str(keyword).strip()
        ]

        max_items = max(1, min(max_items, 200))
        username = parse_shop_username(shop_url)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": shop_url,
            "X-Requested-With": "XMLHttpRequest",
        }

        async with AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=headers,
        ) as client:

            # Langkah 1: Cari shop_id berdasarkan username.
            shop_id = None
            shop_api = f"{SHOP_DOMAIN}/api/v4/shop/get_shop_base_v2"

            Actor.log.info(
                f"Mencari ID toko untuk username: {username}"
            )

            try:
                shop_response = await client.post(
                    shop_api,
                    json={
                        "username": username,
                        "request_source": "mobile_shop_home_page",
                        "livestream_params": {},
                    },
                )

                Actor.log.info(
                    f"Status HTTP pencarian toko: "
                    f"{shop_response.status_code}"
                )
                shop_response.raise_for_status()

                shop_payload = shop_response.json()
                shop_data = shop_payload.get("data") or {}
                shop_id = shop_data.get("shopid")

                if not shop_id:
                    Actor.log.warning(
                        "ID toko tidak ditemukan dalam respons API."
                    )

            except Exception as exc:
                Actor.log.warning(
                    f"Gagal mengambil ID toko: {exc}"
                )

            if not shop_id:
                Actor.log.error(
                    "Tidak dapat melanjutkan karena shop_id belum "
                    "diperoleh. Shopee mungkin membatasi permintaan "
                    "atau mengubah format API."
                )
                return

            Actor.log.info(f"Shop ID ditemukan: {shop_id}")

            # Langkah 2: Ambil produk toko secara bertahap.
            products_api = f"{SHOP_DOMAIN}/api/v4/shop/rcmd_items"
            offset = 0
            page_size = min(max_items, 30)
            saved_keys = set()
            saved_count = 0

            while saved_count < max_items:
                params = {
                    "shop_id": shop_id,
                    "limit": page_size,
                    "offset": offset,
                    "sort_type": 1,
                }

                Actor.log.info(
                    f"Mengambil produk toko: offset={offset}"
                )

                try:
                    response = await client.get(
                        products_api,
                        params=params,
                    )

                    Actor.log.info(
                        f"Status HTTP daftar produk: "
                        f"{response.status_code}"
                    )
                    response.raise_for_status()

                    payload = response.json()

                    if payload.get("error"):
                        Actor.log.warning(
                            f"API mengembalikan error: "
                            f"{payload.get('error_msg')}"
                        )
                        break

                    items = parse_products(payload)

                    if not items:
                        Actor.log.warning(
                            "Tidak ada produk pada halaman ini. "
                            "Format respons mungkin berubah."
                        )
                        break

                    matched_on_page = 0

                    for item in items:
                        if not isinstance(item, dict):
                            continue

                        # Jika keyword kosong, simpan semua produk.
                        item_name = str(item.get("name", "")).lower()

                        matching_keywords = [
                            kw for kw in keywords
                            if kw in item_name
                        ]

                        if keywords and not matching_keywords:
                            continue

                        # Jika satu produk cocok dengan beberapa keyword,
                        # simpan sekali untuk setiap keyword yang cocok.
                        keywords_to_save = (
                            matching_keywords if keywords else [""]
                        )

                        for keyword in keywords_to_save:
                            record = normalize_product(
                                item, keyword, shop_url
                            )
                            if not record:
                                continue

                            unique_key = (
                                record.get("shop_id"),
                                record.get("item_id"),
                                keyword,
                            )

                            if unique_key in saved_keys:
                                continue

                            await Actor.push_data(record)
                            saved_keys.add(unique_key)
                            saved_count += 1
                            matched_on_page += 1

                            if saved_count >= max_items:
                                break

                        if saved_count >= max_items:
                            break

                    Actor.log.info(
                        f"Produk cocok pada halaman ini: "
                        f"{matched_on_page}"
                    )

                    if len(items) < page_size:
                        break

                    offset += len(items)

                except Exception as exc:
                    Actor.log.exception(
                        f"Gagal mengambil daftar produk: {exc}"
                    )
                    break

        Actor.log.info(
            f"Selesai. Total record produk disimpan: {saved_count}"
        )
