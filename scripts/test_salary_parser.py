from app.jobs.parsing.salary import parse_salary

test_cases = [
    "5-7 years of experience",
    "Requires 8–12 years in backend systems",
    "3-5 years",
    "0-1 year",
    "Candidate with 2-5 yrs",
    "$1 - $1",
    "Salary: $140,000 - $180,000 per year",
    "$120k - $160k/yr",
    "$70 - $90/hr",
    "Offering $150,000 annually",
    "USD 65 per hour",
    "Competitive benefits and 401(k) matching",
    "5-7",
    "2-5",
    "8–12",
]

for tc in test_cases:
    res = parse_salary(tc)
    print(f"{tc!r:45} -> min={res[0]}, max={res[1]}, curr={res[2]}, period={res[3]}, text={res[4]!r}")
