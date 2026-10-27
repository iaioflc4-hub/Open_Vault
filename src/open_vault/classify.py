from __future__ import annotations

import re

CATEGORIES = {
    "Tecnología": ("software", "programación", "tecnología", "inteligencia artificial", "computer", "technology", "python", "open source"),
    "Ciencia": ("investigación", "estudio", "ciencia", "científico", "science", "research", "paper"),
    "Negocios": ("empresa", "mercado", "negocio", "finanzas", "business", "company", "economy"),
    "Salud": ("salud", "medicina", "clínica", "health", "medical", "patient"),
    "Educación": ("educación", "aprendizaje", "curso", "education", "learning", "university"),
}


def classify(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.casefold())
    scores = {category: sum(normalized.count(term) for term in terms) for category, terms in CATEGORIES.items()}
    category, score = max(scores.items(), key=lambda item: item[1])
    return category if score else "Por clasificar"
