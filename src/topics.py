"""Research-topic vocabulary used for transparent fit scoring.

Each topic has *strong* keywords (specific evidence) and *weak* keywords (broad,
supporting evidence). Matching is plain keyword matching on whole words, so every
score can be explained by quoting the words that matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TOPICS: dict[str, dict] = {
    "community_nutrition": {
        "label": "public and community nutrition",
        "core": True,
        "strong": [
            "community nutrition", "public health nutrition", "community-based nutrition", "nutrition program",
            "nutrition programs", "snap", "snap-ed", "wic", "school meal", "school meals", "school lunch",
            "school nutrition", "school food", "nutrition policy", "food policy", "nutrition education",
            "food assistance", "nutrition assistance", "food environment", "food environments",
            "community nutrition education", "extension", "cooperative extension", "global nutrition",
            "population nutrition", "food systems", "community health workers", "healthy eating",
            "nutrition awareness", "nutritional awareness", "healthy eating habits",
        ],
        "weak": [
            "public health", "community health", "health promotion", "community-based", "community",
            "policy", "population health", "behavior change", "intervention programs", "lifestyle",
        ],
    },
    "food_insecurity": {
        "label": "food insecurity and nutrition equity",
        "core": True,
        "strong": [
            "food insecurity", "food security", "food insecure", "food access", "food desert", "food deserts",
            "hunger", "food bank", "food banks", "food pantry", "food pantries", "nutrition security",
            "nutrition insecurity", "food is medicine", "produce prescription", "produce prescriptions",
            "nutrition disparities", "nutrition equity", "food justice", "household food security",
        ],
        "weak": [
            "health equity", "health disparities", "disparities", "inequities", "inequity", "low-income",
            "poverty", "social determinants", "underserved", "socioeconomic", "rural", "minority",
            "indigenous", "native american",
        ],
    },
    "maternal_nutrition": {
        "label": "maternal and pregnancy nutrition",
        "core": True,
        "strong": [
            "maternal nutrition", "maternal", "pregnancy", "pregnant", "prenatal", "perinatal", "postpartum",
            "gestational", "gestational weight gain", "lactation", "breastfeeding", "breast milk", "human milk",
            "infant feeding", "infant nutrition", "first 1,000 days", "first 1000 days", "preconception",
            "birth outcomes", "maternal and child", "mother-infant", "early life nutrition", "infancy",
        ],
        "weak": ["women's health", "infant", "infants", "early childhood", "child development", "mothers"],
    },
    "diabetes_metabolic": {
        "label": "diabetes prevention and metabolic health",
        "core": True,
        "strong": [
            "diabetes", "diabetic", "prediabetes", "type 2 diabetes", "gestational diabetes", "glycemic",
            "glucose", "insulin", "insulin resistance", "metabolic health", "metabolic syndrome",
            "cardiometabolic", "obesity", "adiposity", "weight management", "weight loss", "energy balance",
            "metabolism", "hba1c", "blood sugar",
        ],
        "weak": [
            "cardiovascular", "hypertension", "blood pressure", "chronic disease", "chronic diseases",
            "body composition", "lipids", "cholesterol", "inflammation", "metabolic",
        ],
    },
    "childhood_obesity": {
        "label": "childhood obesity",
        "core": True,
        "strong": [
            "childhood obesity", "pediatric obesity", "child obesity", "adolescent obesity", "youth obesity",
            "childhood overweight", "obesity prevention in children", "early childhood obesity",
        ],
        "weak": [],
    },
    "clinical_nutrition": {
        "label": "clinical nutrition and nutrition interventions",
        "core": True,
        "strong": [
            "clinical nutrition", "medical nutrition therapy", "malnutrition", "enteral", "parenteral",
            "nutrition support", "dietary intervention", "dietary interventions", "nutrition intervention",
            "nutrition interventions", "feeding trial", "feeding trials", "randomized controlled trial",
            "randomized controlled trials", "clinical trial", "clinical trials", "renal nutrition",
            "kidney disease", "chronic kidney disease", "oncology nutrition", "nutrition counseling",
            "lifestyle intervention", "lifestyle interventions", "dietetics", "dietitian", "dietitians",
            "nutritional assessment", "nutrition care process", "sarcopenia", "time-restricted eating",
            "diet planning", "diet plan", "diet plans", "therapeutic diet", "meal plans", "renal diet",
        ],
        "weak": ["patients", "patient", "hospital", "clinical", "intervention", "interventions", "trial", "trials", "nutritionist"],
    },
    "nutrition_epidemiology": {
        "label": "nutrition epidemiology",
        "core": True,
        "strong": [
            "nutritional epidemiology", "nutrition epidemiology", "dietary assessment", "dietary patterns",
            "dietary pattern", "diet quality", "dietary intake", "biomarkers of intake", "nhanes",
            "food frequency", "diet and disease", "cohort study", "cohort studies", "prospective cohort",
            "epidemiology", "epidemiologic", "epidemiological",
        ],
        "weak": ["cohort", "cohorts", "population-based", "surveillance", "biostatistics", "biomarkers", "survey", "surveys"],
    },
    "ai_ml": {
        "label": "AI/ML and data science methods",
        "core": False,
        "strong": [
            "machine learning", "artificial intelligence", "deep learning", "data science", "predictive model",
            "predictive models", "predictive modeling", "precision nutrition", "computer vision",
            "natural language processing", "neural network", "neural networks", "ai", "digital health",
            "mhealth", "mobile health", "wearable", "wearables", "continuous glucose monitoring",
            "image-based dietary assessment", "big data", "ml", "xgboost", "shap", "random forest",
            "supervised learning",
        ],
        "weak": ["statistical modeling", "modeling", "bioinformatics", "informatics", "technology", "app-based",
                 "computational", "python"],
    },
}

_CHILD_WORDS = [
    "child", "children", "childhood", "pediatric", "paediatric", "adolescent", "adolescents", "youth",
    "kids", "preschool", "school-age", "school-aged", "early childhood", "infant", "toddler", "toddlers",
]
_WEIGHT_WORDS = ["obesity", "overweight", "weight", "bmi", "adiposity"]


def _compile(word: str) -> re.Pattern:
    escaped = re.escape(word.lower()).replace(r"\ ", r"[\s-]+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


_PATTERNS = {
    key: {
        "strong": [(w, _compile(w)) for w in spec["strong"]],
        "weak": [(w, _compile(w)) for w in spec["weak"]],
    }
    for key, spec in TOPICS.items()
}
_CHILD_PATTERNS = [(w, _compile(w)) for w in _CHILD_WORDS]
_WEIGHT_PATTERNS = [(w, _compile(w)) for w in _WEIGHT_WORDS]


@dataclass
class TopicMatch:
    topic: str
    strong: list[str] = field(default_factory=list)
    weak: list[str] = field(default_factory=list)

    @property
    def is_strong(self) -> bool:
        return bool(self.strong)

    @property
    def label(self) -> str:
        return TOPICS[self.topic]["label"]

    def evidence_words(self, limit: int = 3) -> str:
        words = (self.strong or self.weak)[:limit]
        return ", ".join(f"'{w}'" for w in words)


def match_topics(text: str) -> dict[str, TopicMatch]:
    """Return {topic_key: TopicMatch} for every topic with at least one keyword hit."""
    lowered = (text or "").lower()
    results: dict[str, TopicMatch] = {}
    for key, pats in _PATTERNS.items():
        strong = [w for w, p in pats["strong"] if p.search(lowered)]
        weak = [w for w, p in pats["weak"] if p.search(lowered)]
        if strong or weak:
            results[key] = TopicMatch(key, strong, weak)
    # Composite rule: weight/obesity words + child words => childhood obesity.
    if "childhood_obesity" not in results or not results["childhood_obesity"].strong:
        weights = [w for w, p in _WEIGHT_PATTERNS if p.search(lowered)]
        kids = [w for w, p in _CHILD_PATTERNS if p.search(lowered)]
        if weights and kids:
            m = results.setdefault("childhood_obesity", TopicMatch("childhood_obesity"))
            m.strong.append(f"{weights[0]} + {kids[0]}")
    # Short words such as 'ai' and 'ml' only count when written in capitals in the original text.
    if "ai_ml" in results:
        m = results["ai_ml"]
        for short in ("ai", "ml"):
            if short in m.strong and not re.search(rf"(?<![A-Za-z]){short.upper()}(?![A-Za-z])", text or ""):
                m.strong.remove(short)
        if not m.strong and not m.weak:
            del results["ai_ml"]
    return results


def topic_label(key: str) -> str:
    return TOPICS.get(key, {}).get("label", key.replace("_", " "))


def core_topics(matches: dict[str, TopicMatch]) -> dict[str, TopicMatch]:
    return {k: v for k, v in matches.items() if TOPICS[k]["core"]}
