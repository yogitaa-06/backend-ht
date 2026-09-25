import logging
from typing import Any

from playwright.async_api import async_playwright

from app.domain.jobs import JobSource
from app.jobs.errors import SourceBlockedError
from app.jobs.normalization import RawSourceJob

logger = logging.getLogger(__name__)

class HiringCafeCollector:
    source = JobSource.HIRINGCAFE

    def __init__(self, *, client: Any = None):
        # We don't use httpx client because Playwright is required
        pass

    async def collect(self, target: Any) -> list[RawSourceJob]:
        from app.core.config import get_settings
        settings = get_settings()
        
        yielded_jobs = []
        
        async with async_playwright() as p:
            # We must use Playwright to bypass Cloudflare Turnstile and Next.js RSC streaming
            proxy_url = getattr(settings, "JOB_COLLECTION_PROXY_URL", None)
            proxy_settings = {"server": proxy_url} if proxy_url else None
            
            browser = await p.chromium.launch(headless=True, proxy=proxy_settings) # type: ignore
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/117.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720}
            )
            
            # Navigate directly to search query
            # We'll use a fixed query for demonstration, but this can be parameterized
            page = await context.new_page()
            try:
                logger.info("Navigating to HiringCafe search...")
                res = await page.goto(
                    "https://hiringcafe.com/search?q=Software+Engineer",
                    wait_until="domcontentloaded",
                    timeout=30000
                )
                if res and res.status == 403:
                    raise SourceBlockedError("HiringCafe blocked the request with 403 Forbidden.")
                
                # Wait for jobs to populate in the DOM
                await page.wait_for_timeout(3000)
                
                # Check for Cloudflare block
                page_text = await page.evaluate("document.body.innerText")
                if "Performance and Security by Cloudflare" in page_text:
                    raise SourceBlockedError("HiringCafe Cloudflare challenge detected.")
                
                # Extract all job links from the page
                links = await page.locator("a[href*='/job/']").all()
                job_urls = []
                for link in links:
                    href = await link.get_attribute("href")
                    if href and href not in job_urls:
                        job_urls.append(href)
                        
                logger.info(f"Discovered {len(job_urls)} jobs on HiringCafe.")
                
                max_jobs = getattr(settings, "JOB_COLLECTION_MAX_JOBS_PER_TARGET", 5)
                for _, url in enumerate(job_urls[:max_jobs]):
                    full_url = f"https://hiringcafe.com{url}"
                    try:
                        job_page = await context.new_page()
                        await job_page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
                        await job_page.wait_for_timeout(1000) # Ensure hydration
                        
                        # Extract basic text fields using robust generic selectors
                        text_content = await job_page.evaluate("document.body.innerText")
                        lines = [line.strip() for line in text_content.split("\\n") if line.strip()]
                        
                        # Robust fallback parsing since they don't have standard classes or JSON-LD
                        # Best effort from known layout
                        title = lines[4] if len(lines) > 4 else "Software Engineer"
                        company = lines[5] if len(lines) > 5 else "Unknown Company"
                        location = lines[6] if len(lines) > 6 else "Remote"
                        
                        job = RawSourceJob(
                            source=self.source,
                            external_job_id=url.split("-")[-1],
                            title=title,
                            company=company,
                            location=location,
                            url=full_url,
                            raw_data={"extracted_text": "\\n".join(lines[:20])}
                        )
                        yielded_jobs.append(job)
                        await job_page.close()
                    except Exception as e:
                        logger.error(f"Failed to extract HiringCafe job {full_url}: {e}")
                
            except Exception as e:
                if isinstance(e, SourceBlockedError):
                    raise
                logger.error(f"HiringCafe collection failed: {e}")
            finally:
                await browser.close()
            
            return yielded_jobs
