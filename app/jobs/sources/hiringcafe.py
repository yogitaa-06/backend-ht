import datetime
import json
import logging
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import async_playwright

from app.core.config import get_settings
from app.domain.jobs import JobSource
from app.jobs.errors import SourceBlockedError
from app.jobs.normalization import RawSourceJob
from app.jobs.parsing.employment_type import (
    normalize_employment_type,
    normalize_remote_type,
)
from app.jobs.parsing.experience import extract_experience
from app.jobs.parsing.salary import parse_salary
from app.jobs.parsing.skills import extract_skills_from_text

logger = logging.getLogger(__name__)


class HiringCafeCollector:
    source = JobSource.HIRINGCAFE

    def __init__(self, *, client: Any = None):
        # We don't use httpx client because Playwright is required
        pass

    async def collect(self, target: Any) -> list[RawSourceJob]:
        settings = get_settings()
        yielded_jobs: list[RawSourceJob] = []

        async with async_playwright() as p:
            # We must use Playwright to bypass Cloudflare Turnstile and Next.js RSC streaming
            proxy_url = getattr(settings, "JOB_COLLECTION_PROXY_URL", None)
            proxy_settings = {"server": proxy_url} if proxy_url else None

            browser = await p.chromium.launch(headless=True, proxy=proxy_settings)  # type: ignore
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/117.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )

            # Navigate directly to search query
            page = await context.new_page()
            try:
                logger.info("Navigating to HiringCafe search...")

                # Build URL with query and location
                search_url = f"https://hiringcafe.com/search?q={quote_plus(target.query)}"
                loc = getattr(target, "location", None) or "United States"
                if loc:
                    search_url += f"&l={quote_plus(loc)}"

                res = await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                if res and res.status == 403:
                    raise SourceBlockedError("HiringCafe blocked the request with 403 Forbidden.")

                # Wait for jobs to populate in the DOM
                await page.wait_for_timeout(3000)

                # Check for Cloudflare block
                page_text = await page.evaluate("document.body.innerText")
                if "Performance and Security by Cloudflare" in page_text:
                    raise SourceBlockedError("HiringCafe Cloudflare challenge detected.")

                logger.info("Extracting NEXT_DATA from search page...")
                try:
                    js = 'document.getElementById("__NEXT_DATA__").innerText'
                    next_data_json = await page.evaluate(js)
                except Exception as e:
                    logger.error(f"Failed to find NEXT_DATA: {e}")
                    next_data_json = None

                max_jobs = getattr(
                    target, "max_jobs", getattr(settings, "JOB_COLLECTION_MAX_JOBS_PER_TARGET", 5)
                )

                if next_data_json:
                    data = json.loads(next_data_json)
                    ssr_hits = data.get("props", {}).get("pageProps", {}).get("ssrHits", [])
                    logger.info(f"Discovered {len(ssr_hits)} jobs in NEXT_DATA.")

                    for hit in ssr_hits:
                        if len(yielded_jobs) >= max_jobs:
                            break

                        try:
                            job_info = hit.get("job_information", {})
                            v5 = hit.get("v5_processed_job_data", {})

                            external_id = hit.get("id")
                            if not external_id:
                                continue

                            base_title = job_info.get("title") or v5.get("core_job_title")
                            title = base_title or "Unknown Title"
                            company = v5.get("company_name")
                            location = v5.get("formatted_workplace_location")
                            url = (
                                hit.get("apply_url") or f"https://hiringcafe.com/job/{external_id}"
                            )

                            commitment = v5.get("commitment")
                            raw_emp = commitment[0] if (commitment and isinstance(commitment, list)) else None
                            emp_type = raw_emp if (raw_emp and raw_emp.strip()) else None

                            reqs = v5.get("requirements_summary")
                            roles = v5.get("role_activities")
                            desc_parts = []
                            if reqs:
                                desc_parts.append(f"Requirements:\n{reqs}")
                            if roles and isinstance(roles, list):
                                desc_parts.append("Activities:\n- " + "\n- ".join(roles))
                            description = "\n\n".join(desc_parts) if desc_parts else None

                            if not emp_type and description:
                                emp_type = normalize_employment_type(description)

                            tech_tools = [str(t) for t in (v5.get("technical_tools") or []) if t]
                            text_skills = list(extract_skills_from_text(f"{title}\n{description or ''}"))
                            combined_skills: list[str] = []
                            for sk in tech_tools + text_skills:
                                if sk not in combined_skills:
                                    combined_skills.append(sk)
                            skills = tuple(combined_skills)

                            sal_min, sal_max, sal_curr, sal_period, sal_text = parse_salary(description)
                            exp_min, exp_max, exp_text = extract_experience(f"{title}\n{description or ''}")

                            remote_type = normalize_remote_type(f"{location or ''}\n{title}\n{description or ''}")
                            remote = (
                                True
                                if remote_type == "remote"
                                else (False if remote_type in ("hybrid", "onsite") else None)
                            )

                            pub_ms = v5.get("estimated_publish_date_millis")
                            posted_at = None
                            if pub_ms:
                                pub_s = pub_ms / 1000.0
                                posted_at = datetime.datetime.fromtimestamp(pub_s, tz=datetime.UTC)

                            job = RawSourceJob(
                                source=self.source.value,
                                external_job_id=external_id,
                                title=title,
                                company=company,
                                location=location,
                                url=url,
                                description=description,
                                salary_text=sal_text,
                                salary_min=sal_min,
                                salary_max=sal_max,
                                salary_currency=sal_curr,
                                salary_period=sal_period,
                                employment_type=emp_type,
                                remote=remote,
                                remote_type=remote_type,
                                posted_at=posted_at,
                                skills=skills,
                                experience_min_years=exp_min,
                                experience_max_years=exp_max,
                                experience_text=exp_text,
                                raw_data={"next_data": hit},
                            )
                            yielded_jobs.append(job)
                        except Exception as e:
                            logger.error(f"Failed to parse job hit: {e}")

            except Exception as e:
                if isinstance(e, SourceBlockedError):
                    raise
                logger.error(f"HiringCafe collection failed: {e}")
            finally:
                await browser.close()

            return yielded_jobs
