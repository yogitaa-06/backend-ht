"""Deterministic skills extraction and normalization."""

from __future__ import annotations

import re
from collections.abc import Sequence

# Canonical skill representations and their lookup aliases
CANONICAL_SKILLS: dict[str, str] = {
    # Languages
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java": "Java",
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    "golang": "Go",
    "go": "Go",
    "rust": "Rust",
    "ruby": "Ruby",
    "php": "PHP",
    "scala": "Scala",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "dart": "Dart",
    "r": "R",
    "sql": "SQL",
    "nosql": "NoSQL",
    "html": "HTML",
    "html5": "HTML",
    "css": "CSS",
    "css3": "CSS",
    "sass": "Sass",
    "bash": "Bash",
    "shell": "Shell",
    "powershell": "PowerShell",
    # Frameworks & Libraries
    "react": "React",
    "react.js": "React",
    "reactjs": "React",
    "next.js": "Next.js",
    "nextjs": "Next.js",
    "vue": "Vue.js",
    "vue.js": "Vue.js",
    "angular": "Angular",
    "node": "Node.js",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "express": "Express.js",
    "express.js": "Express.js",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "spring": "Spring",
    "spring boot": "Spring Boot",
    "springboot": "Spring Boot",
    ".net": ".NET",
    "dotnet": ".NET",
    "asp.net": "ASP.NET",
    "rails": "Ruby on Rails",
    "ruby on rails": "Ruby on Rails",
    "graphql": "GraphQL",
    "rest": "REST API",
    "restful": "REST API",
    "grpc": "gRPC",
    # Databases & Caching
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "sqlite": "SQLite",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    "cassandra": "Cassandra",
    "dynamodb": "DynamoDB",
    "snowflake": "Snowflake",
    "bigquery": "BigQuery",
    # Cloud & DevOps
    "aws": "AWS",
    "amazon web services": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
    "google cloud": "GCP",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "jenkins": "Jenkins",
    "github actions": "GitHub Actions",
    "gitlab ci": "GitLab CI",
    "circleci": "CircleCI",
    "linux": "Linux",
    "unix": "Unix",
    "git": "Git",
    # Architecture & Messaging
    "microservices": "Microservices",
    "kafka": "Kafka",
    "rabbitmq": "RabbitMQ",
    "sqs": "AWS SQS",
    # AI / ML / Data
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "scikit-learn": "Scikit-Learn",
    "airflow": "Apache Airflow",
    "spark": "Apache Spark",
    # Testing & QA
    "pytest": "PyTest",
    "junit": "JUnit",
    "jest": "Jest",
    "cypress": "Cypress",
    "playwright": "Playwright",
    "selenium": "Selenium",
}

# Compiled regex patterns for skill scanning in free text
_SPECIAL_SKILL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:^|[\s.,;/(])c\+\+(?:$|[\s.,;/):])", re.IGNORECASE), "C++"),
    (re.compile(r"(?:^|[\s.,;/(])c#(?:$|[\s.,;/):])", re.IGNORECASE), "C#"),
    (re.compile(r"(?:^|[\s.,;/(])\.net(?:$|[\s.,;/):])", re.IGNORECASE), ".NET"),
    (re.compile(r"(?:^|[\s.,;/(])go(?:$|[\s.,;/):])", re.IGNORECASE), "Go"),
    (re.compile(r"(?:^|[\s.,;/(])r(?:$|[\s.,;/):])", re.IGNORECASE), "R"),
]


def normalize_skill(skill: str) -> str | None:
    """Normalize a raw skill string to canonical form if recognized or clean casing."""
    cleaned = " ".join(skill.strip().split())
    if not cleaned:
        return None

    lowered = cleaned.casefold()
    if lowered in CANONICAL_SKILLS:
        return CANONICAL_SKILLS[lowered]

    # Return trimmed title-cased if 2-30 chars and not mostly punctuation/garbage
    if 2 <= len(cleaned) <= 40 and re.search(r"[a-zA-Z]", cleaned):
        return cleaned.title()
    return None


def extract_skills_from_list(raw_skills: Sequence[str] | None) -> list[str]:
    """Normalize and deduplicate an explicit list of skills preserving canonical names."""
    if not raw_skills:
        return []

    seen: set[str] = set()
    result: list[str] = []

    for raw in raw_skills:
        if not raw:
            continue
        # Split on commas/semicolons if bundled
        parts = re.split(r"[,;|/]", str(raw))
        for part in parts:
            norm = normalize_skill(part)
            if norm and norm.casefold() not in seen:
                seen.add(norm.casefold())
                result.append(norm)

    return result


def extract_skills_from_text(text: str | None) -> list[str]:
    """Deterministically scan text (e.g. description) for known technical skills."""
    if not text:
        return []

    found: set[str] = set()
    canonical_results: list[str] = []

    # 1. Match special symbols first (C++, C#, .NET, Go, R)
    for pattern, canonical_name in _SPECIAL_SKILL_PATTERNS:
        if pattern.search(text) and canonical_name.casefold() not in found:
            found.add(canonical_name.casefold())
            canonical_results.append(canonical_name)

    # 2. Match standard word skills with word boundaries
    lowered_text = f" {text.casefold()} "
    for alias, canonical_name in CANONICAL_SKILLS.items():
        if canonical_name.casefold() in found:
            continue
        if alias in {"c++", "c#", ".net", "go", "r"}:
            continue  # Handled by special patterns above

        # Check for word boundary around alias
        alias_pattern = rf"(?:\b|\s){re.escape(alias)}(?:\b|\s)"
        if re.search(alias_pattern, lowered_text):
            found.add(canonical_name.casefold())
            canonical_results.append(canonical_name)

    return canonical_results


def merge_skills(
    explicit_skills: Sequence[str] | None,
    text_skills: Sequence[str] | None,
) -> list[str]:
    """Merge explicit skills with text-extracted skills, prioritizing explicit ones."""
    seen: set[str] = set()
    merged: list[str] = []

    for s in extract_skills_from_list(explicit_skills):
        if s.casefold() not in seen:
            seen.add(s.casefold())
            merged.append(s)

    for s in text_skills or []:
        norm = normalize_skill(s) or s
        if norm.casefold() not in seen:
            seen.add(norm.casefold())
            merged.append(norm)

    return merged
