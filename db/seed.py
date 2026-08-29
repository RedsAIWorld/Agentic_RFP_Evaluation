"""
Creates rfp_evaluation.db (if missing) and seeds it with the brief's default
criteria plus the Incumbency & Transition Cost criterion (seeded INACTIVE,
so the app boots in exact brief-compliance mode; toggling incumbency on in
the Criteria screen deliberately pushes active weights to 110% -- a live,
harmless demonstration of the weight-normalization rule).

Safe to re-run: only seeds evaluation_criteria if the table is empty.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "rfp_evaluation.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

DEFAULT_CRITERIA = [
    # (name, description, weight, max_score, scoring_source, is_active, sort_order)
    ("Technical Capability",
     "Architecture, integrations, scalability, technical fit to the stated requirement.",
     30, 10, "llm", 1, 1),
    ("Implementation Plan",
     "Timeline, milestones, staffing plan, risk controls for the transition/rollout.",
     20, 10, "llm", 1, 2),
    ("Commercial Value",
     "Pricing clarity, total cost of ownership, assumptions behind the price table.",
     20, 10, "llm", 1, 3),
    ("Security & Compliance",
     "Controls, certifications, data privacy, auditability.",
     20, 10, "llm", 1, 4),
    ("Support & Experience",
     "Support model, similar past projects, references.",
     10, 10, "llm", 1, 5),
    ("Incumbency & Transition Cost",
     "Deterministic criterion (NOT scored by the LLM): rewards a well-performing "
     "incumbent for the transition cost the buyer avoids by not switching, and "
     "penalizes a poor-performing incumbent for the transition cost the buyer will "
     "eventually pay anyway, on top of current poor delivery. Non-incumbents get a "
     "neutral baseline. See ranking_tool.score_incumbency for the exact rule table.",
     10, 10, "deterministic", 0, 6),  # inactive by default -> brief-compliance mode
]


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with open(SCHEMA_PATH) as f:
        schema = f.read()
    conn = get_connection()
    conn.executescript(schema)
    conn.commit()

    existing = conn.execute("SELECT COUNT(*) FROM evaluation_criteria").fetchone()[0]
    if existing == 0:
        conn.executemany(
            """INSERT INTO evaluation_criteria
               (name, description, weight, max_score, scoring_source, is_active, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            DEFAULT_CRITERIA,
        )
        conn.commit()
        print(f"Seeded {len(DEFAULT_CRITERIA)} criteria into {DB_PATH}")
    else:
        print(f"evaluation_criteria already has {existing} rows -- skipped seeding")

    conn.close()


if __name__ == "__main__":
    init_db()
