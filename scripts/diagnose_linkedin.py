import asyncio
import re

from app.jobs.sources.linkedin import LinkedInCollector


async def main():
    collector = LinkedInCollector()
    client = collector._build_client()
    
    print("--- FETCHING DETAIL ---")
    try:
        response = await client.get('https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4419969671')
    except Exception as e:
        print(f"Fetch failed: {e}")
        return
        
    print(f"1. HTTP status: {response.status_code}")
    print(f"2. Final URL: {response.url}")
    print(f"3. Content-Type: {response.headers.get('content-type', 'Unknown')}")
    print(f"4. Length: {len(response.text)} chars, {len(response.content)} bytes")
    print(f"5. Is empty: {not bool(response.text.strip())}")
    
    # Check for application/ld+json
    title = re.search(r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>', response.text, re.IGNORECASE | re.DOTALL)
    print(f"Title: {title.group(1).strip() if title else 'Not Found'}")
    
    company = re.search(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', response.text, re.IGNORECASE | re.DOTALL)
    if not company:
        company = re.search(r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>', response.text, re.IGNORECASE | re.DOTALL)
    print(f"Company: {company.group(1).strip() if company else 'Not Found'}")
    
    desc = re.search(r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', response.text, re.IGNORECASE | re.DOTALL)
    if not desc:
         desc = re.search(r'<div[^>]*class="[^"]*description__text[^"]*"[^>]*>(.*?)</div>', response.text, re.IGNORECASE | re.DOTALL)
    location = re.findall(r'<span[^>]*class="[^"]*topcard__flavor topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>', response.text, re.IGNORECASE | re.DOTALL)
    print(f"Location: {location[0].strip() if location else 'Not Found'}")
    
    posted_at = re.search(r'<span[^>]*class="[^"]*posted-time-ago__text[^"]*"[^>]*>(.*?)</span>', response.text, re.IGNORECASE | re.DOTALL)
    print(f"Posted At: {posted_at.group(1).strip() if posted_at else 'Not Found'}")
    
    emp_type = re.search(r'<li[^>]*class="[^"]*description__job-criteria-item[^"]*"[^>]*>.*?Employment type.*?<span[^>]*class="[^"]*description__job-criteria-text[^"]*"[^>]*>(.*?)</span>', response.text, re.IGNORECASE | re.DOTALL)
    print(f"Employment Type: {emp_type.group(1).strip() if emp_type else 'Not Found'}")
    
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
