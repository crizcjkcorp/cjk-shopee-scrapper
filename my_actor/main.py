
from __future__ import annotations

from urllib.parse import quote

from apify import Actor
from httpx2 import AsyncClient


COUNTRY_DOMAINS = {
    "ID": "https://shopee.co.id",
    "SG": "https://shopee.sg",
    "MY": "https://shopee.com.my",
    "TH": "https://shopee.co.th",
    "PH": "https://shopee.ph",
    "VN": "https://shopee.vn",
    "TW": "https://shopee.tw",
    "BR": "https://shopee.com.br",
}


def format_price(value):
    """Convert Shopee's integer price representation to a price."""
    if value is None:
        return None

    try:
        return int(value) / 100000
    except (ValueError, TypeError):
        return None


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}

        keywords = actor_input.get("keywords", [])
        country = actor_input.get("country", "ID")
        max_items = int(actor_input.get("maxItems", 20))

        if isinstance(keywords, str):
            keywords = [keywords]

        keywords = [
            str(keyword).strip()
            for keyword in keywords
            if str(keyword).strip()
        ]

        if not keywords:
            raise ValueError(
                "Masukkan minimal satu keyword di input Actor."
            )

        if country not in COUNTRY_DOMAINS:
            raise ValueError(
                f"Country tidak didukung: {country}"
            )

        max_items = max(1, min(max_items, 200))
        domain = COUNTRY_DOMAINS[country]

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": f"{domain}/",
            "X-Requested-With": "XMLHttpRequest",
        }

        async with AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=headers,
        ) as client:

            for keyword in keywords:
                Actor.log.info(
                    f"Mencari produk Shopee: {keyword}"
                )

                endpoint = (
                    f"{domain}/api/v4/search/search_items"
                )

                params = {
                    "by": "relevancy",
                    "keyword": keyword,
                    "limit": min(max_items, 60),
                    "newest": 0,
                    "order": "desc",
                    "page_type": "search",
                    "scenario": "PAGE_GLOBAL_SEARCH",
                    "version": 2,
                }

                try:
                    response = await client.get(
                        endpoint,
                        params=params,
                    )

                    Actor.log.info(
                        f"HTTP status untuk '{keyword}': "
                        f"{response.status_code}"
                    )

                    response.raise_for_status()
                    payload = response.json()

                    if not isinstance(payload, dict):
                        raise ValueError(
                            "Respons Shopee bukan JSON object."
                        )

                    data = payload.get("items")

                    if data is None:
                        data = (
                            payload.get("data", {}).get("items", [])
                            if isinstance(payload.get("data"), dict)
                            else []
                        )

                    if not isinstance(data, list):
                        data = []

                    if not data:
                        Actor.log.warning(
                            f"Tidak ada produk ditemukan untuk "
                            f"'{keyword}'. Respons mungkin berubah "
                            "atau akses dibatasi Shopee."
                        )
                        continue

                    saved = 0

                    for result in data[:max_items]:
                        if not isinstance(result, dict):
                            continue

                        item = result.get("item_basic", result)

                        if not isinstance(item, dict):
                            continue

                        item_id = item.get("itemid")
                        shop_id = item.get("shopid")

                        name = item.get("name")

                        if not name:
                            continue

                        price_min = format_price(
                            item.get("price_min", item.get("price"))
                        )
                        price_max = format_price(
                            item.get("price_max", item.get("price"))
                        )

                        rating_info = item.get("item_rating") or {}

                        if not isinstance(rating_info, dict):
                            rating_info = {}

                        if item_id and shop_id:
                            product_url = (
                                f"{domain}/product/"
                                f"{shop_id}/{item_id}"
                            )
                        else:
                            product_url = None

                        image_id = item.get("image")
                        image_url = (
                            f"https://down-{country.lower()}.img.susercontent.com/"
                            f"file/{image_id}"
                            if image_id
                            else None
                        )

                        record = {
                            "keyword": keyword,
                            "country": country,
                            "product_name": name,
                            "price_min": price_min,
                            "price_max": price_max,
                            "currency": (
                                "IDR" if country == "ID"
                                else None
                            ),
                            "shop_name": item.get("shop_name"),
                            "shop_id": shop_id,
                            "item_id": item_id,
                            "rating": rating_info.get("rating_star"),
                            "rating_count": item.get("cmt_count"),
                            "sold": item.get(
                                "historical_sold",
                                item.get("sold"),
                            ),
                            "product_url": product_url,
                            "image_url": image_url,
                        }

                        await Actor.push_data(record)
                        saved += 1

                    Actor.log.info(
                        f"Keyword '{keyword}': "
                        f"{saved} produk disimpan."
                    )

                except Exception as exc:
                    Actor.log.exception(
                        f"Gagal mencari '{keyword}': {exc}"
                    )

        Actor.log.info("Scraping selesai.")
