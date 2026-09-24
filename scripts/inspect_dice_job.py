"""Inspect one live Dice job-detail response."""

from __future__ import annotations

import asyncio
import json
import re

import httpx

JOB_URL = "https://www.dice.com/job-detail/ce3f6f92-ed77-4a64-91d0-dedab5a990f5"


async def main() -> None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/153.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        timeout=20.0,
    ) as client:
        response = await client.get(JOB_URL)

    print("=" * 100)
    print("DICE DETAIL INSPECTION")
    print("=" * 100)

    print(f"Status       : {response.status_code}")
    print(f"Final URL    : {response.url}")
    print(f"Content-Type : {response.headers.get('content-type')}")
    print(f"HTML Length  : {len(response.text)}")

    html = response.text

    print()
    print("Important terms found:")
    print("-" * 100)

    terms = [
        "JobPosting",
        "datePosted",
        "hiringOrganization",
        "jobLocation",
        "employmentType",
        "description",
        "skills",
        "__NEXT_DATA__",
        "application/ld+json",
    ]

    for term in terms:
        print(f"{term:25}: {term.lower() in html.lower()}")

    print()
    print("JSON-LD blocks:")
    print("-" * 100)

    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
        r"(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    print(f"JSON-LD block count: {len(blocks)}")

    for index, block in enumerate(blocks, start=1):
        print()
        print(f"JSON-LD #{index}")

        try:
            data = json.loads(block.strip())

            if isinstance(data, dict):
                print(
                    json.dumps(
                        data,
                        indent=2,
                        ensure_ascii=False,
                    )[:8000]
                )
            else:
                print(
                    json.dumps(
                        data,
                        indent=2,
                        ensure_ascii=False,
                    )[:8000]
                )

        except json.JSONDecodeError as exc:
            print(f"Could not decode JSON-LD: {exc}")
            print(block.strip()[:2000])


if __name__ == "__main__":
    asyncio.run(main())
