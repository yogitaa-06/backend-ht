import asyncio
import re
from urllib.parse import urlparse
from app.jobs.sources.linkedin import LinkedInCollector
from app.jobs.targets import CollectionTarget
from app.domain.jobs import JobSource

async def main():
    target = CollectionTarget(
        source=JobSource.LINKEDIN,
        query="Software Engineer",
        location="United States",
        max_jobs=10
    )
    
    collector = LinkedInCollector()
    client = collector._build_client()
    
    try:
        response = await collector._fetch_search_page(client, target=target, start=0)
    except Exception as e:
        print(f"Fetch failed: {e}")
        return
        
    links = re.findall(r'<a[^>]+href=["\']([^"\']*/jobs/view/[^"\']*)["\']', response.text, re.IGNORECASE)
    
    for i, href in enumerate(links[:10], 1):
        parsed = urlparse(href)
        path = parsed.path
        
        # Current broken logic simulation:
        match = re.search(r'/jobs/view/(?:[^"\'?]*?-)?(\d+)', href)
        extracted_id = match.group(1) if match else "None"
        
        print(f"{i}\nhref:\n{href}\npathname:\n{path}\nextracted_external_job_id:\n{extracted_id}\n")
    
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
