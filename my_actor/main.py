```python
from __future__ import annotations

from apify import Actor
from httpx2 import AsyncClient

SHOP_URL = "https://shopee.co.id/waterlilyliterary"
SHOP_USERNAME = "waterlilyliterary"
SHOP_DOMAIN = "https://shopee.co.id"


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}

        keywords = actor_input.get("keywords", [])
        max_items = int(actor_input.get("maxItems", 20))

        if isinstance(keywords, str):
            keywords = [keywords]

        keywords = [
            str(keyword).strip().lower()
            for keyword in keywords
            if str(keyword).strip()
        ]

        if not keywords:
            raise ValueError(
                "Masukkan minimal satu keyword di input Actor."
            )

        max_items = max(1, min(max_items, 200))

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/json",
            "Referer": SHOP_URL,
        }

        async with AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=headers,
        ) as client:

            Actor.log.info(
                f"Mengakses toko Shopee: {SHOP_URL}"
            )

            response = await client.get(SHOP_URL)

            Actor.log.info(
                f"Status HTTP halaman toko: {response.status_code}"
            )

            response.raise_for_status()

            Actor.log.info(
                "Halaman toko berhasil diakses. "
                "Namun halaman HTML belum tentu berisi seluruh produk."
            )

            # Catatan:
            # Halaman profil toko saja tidak menjamin data produk
            # tersedia dalam HTML. Endpoint produk toko Shopee
            # perlu diverifikasi sebelum data bisa diambil.

            Actor.log.warning(
                "Belum ada produk yang disimpan. "
                "Endpoint daftar produk toko belum diimplementasikan."
            )

        Actor.log.info("Proses selesai.")
```
