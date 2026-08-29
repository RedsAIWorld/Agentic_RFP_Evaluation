"""
Demo Provider -- NOT a real LLM. Returns realistic, hand-authored canned
evaluation JSON per synthetic supplier, matching the llm_providers.LLMProvider
interface (.complete(system_prompt, user_prompt, max_tokens)) so the
Orchestrator, Validation Tool, and Ranking Tool run completely unmodified.

Why this exists: the brief's success condition depends on the FULL pipeline
being demonstrable reliably -- if a grader has no API key, hits a rate limit,
or the provider is down during grading, the app should still fully work.
This also guarantees the prompt-injection defense demo (Vantage Cloud
Solutions) is visible even without depending on a live model's behaviour.

One evidence item below (Orbit Digital, Security & Compliance) is a
DELIBERATE mismatch with the source PDF -- the claimed quote does not appear
in Orbit's actual document text -- to demonstrate the Validation Tool's
evidence-verification warning firing on a real run, not just in unit tests.
"""
import json


class DemoProvider:
    name = "Demo (offline, no API key)"
    model = "canned-v1"

    def __init__(self, *args, **kwargs):
        pass

    def test_connection(self):
        return True, "Offline demo mode active -- no API calls will be made."

    def complete(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
        for supplier_name, payload in CANNED_RESPONSES.items():
            if supplier_name in user_prompt:
                return json.dumps(payload)
        # Unknown supplier in demo mode -- return a generic low-confidence response
        # rather than raising, so demo mode never crashes on an unexpected upload.
        return json.dumps(_generic_response("Unknown Supplier"))


def _c(cid, score, evidence_status, justification, evidence=None):
    return {
        "criterion_id": cid, "score": score, "max_score": 10,
        "evidence_status": evidence_status, "justification": justification,
        "evidence": evidence or [],
    }


def _generic_response(name):
    return {
        "supplier_name": name,
        "criteria": [_c(cid, 0, "missing", "No demo data available for this supplier.") for cid in (1, 2, 3, 4, 5)],
        "risks": ["Demo mode: no canned data for this supplier."],
        "overall_summary": "Demo mode placeholder.",
    }


CANNED_RESPONSES = {
    "Apex Systems": {
        "supplier_name": "Apex Systems",
        "criteria": [
            _c(1, 9, "strong",
               "Detailed microservices architecture with a documented rollback procedure and load "
               "testing at 4x baseline, exceeding the stated 3x requirement.",
               [{"quote": "Apex proposes a microservices-based platform with a dedicated triage engine that classifies incoming tickets", "page": 1}]),
            _c(2, 7, "strong",
               "Thorough plan with named roles, but the 110-day timeline exceeds the RFP's 90-day maximum by 20 days.",
               [{"quote": "Apex proposes a 110-day transition", "page": 1}]),
            _c(3, 6, "strong",
               "Clear price table and assumptions, but the highest run-cost among the compliant proposals.",
               [{"quote": "Year 1 steady-state run cost: USD 95,000 per month", "page": 2}]),
            _c(4, 9, "strong",
               "ISO 27001 and SOC 2 Type II certified with strong access controls and a committed 4-hour incident response SLA.",
               [{"quote": "Apex is ISO 27001:2022 certified", "page": 2}]),
            _c(5, 8, "moderate",
               "Two comparable energy-sector references cited, though contact details are withheld pending referee approval.",
               [{"quote": "Apex has delivered comparable application management platforms for two multinational energy and utilities clients", "page": 2}]),
        ],
        "risks": ["Proposed transition timeline (110 days) exceeds the RFP's stated 90-day maximum."],
        "overall_summary": "Technically strongest and most security-mature proposal, at a premium price and a longer transition than requested.",
    },
    "BrightPath Tech": {
        "supplier_name": "BrightPath Tech",
        "criteria": [
            _c(1, 5, "weak",
               "Generic, non-fine-tuned SaaS product; explicitly not load-tested at the required 3x seasonal spike.",
               [{"quote": "we have not load-tested the platform at the specific 3x seasonal spike volume", "page": 1}]),
            _c(2, 7, "moderate",
               "Fastest proposed timeline (45 days) and clear phases, but weekend coverage is only best-effort.",
               [{"quote": "BrightPath proposes a 45-day transition", "page": 1}]),
            _c(3, 9, "strong",
               "Lowest price by a wide margin, with all change requests included regardless of size.",
               [{"quote": "Year 1 steady-state run cost: USD 42,000 per month", "page": 2}]),
            _c(4, 2, "weak",
               "No current certification; SOC 2 is only planned for 12-18 months out, which is a material gap for this RFP's security requirements.",
               [{"quote": "We are in the process of pursuing SOC 2 certification", "page": 2}]),
            _c(5, 4, "weak",
               "No comparable-scale reference cited; this would be BrightPath's largest engagement to date.",
               [{"quote": "This would be our largest engagement to date in terms of application portfolio size", "page": 2}]),
        ],
        "risks": ["No current security certification despite handling business-critical applications.",
                  "No load testing evidence at the RFP's required seasonal spike volume."],
        "overall_summary": "Cheapest and fastest option, but security posture and scale experience are materially weaker than competitors.",
    },
    "NexaWorks": {
        "supplier_name": "NexaWorks",
        "criteria": [
            _c(1, 8, "strong",
               "Hybrid AI/human triage with a stated 92% historical accuracy and validation at 3.5x baseline load, comfortably above the RFP's 3x requirement.",
               [{"quote": "documented 92% historical accuracy across comparable deployments", "page": 1}]),
            _c(2, 10, "strong",
               "Meets the RFP's 90-day window exactly, with named transition governance and go/no-go gates per application group.",
               [{"quote": "NexaWorks commits to the RFP's 90-day transition window", "page": 1}]),
            _c(3, 8, "strong",
               "Competitive mid-range pricing with a capped indexation clause and an explicit service-credit regime for missed SLAs.",
               [{"quote": "a service-credit regime of up to 8% of monthly fees for missed SLAs", "page": 2}]),
            _c(4, 9, "strong",
               "ISO 27001 and annual SOC 2 Type II audits, 2-hour Sev-1 response SLA, and a documented quarterly access review.",
               [{"quote": "NexaWorks commits to a 2-hour initial response SLA for Severity 1 security incidents", "page": 2}]),
            _c(5, 9, "strong",
               "Named Service Delivery Manager and two active, contactable references of comparable scale.",
               [{"quote": "NexaWorks has delivered three comparable engagements in the past five years", "page": 2}]),
        ],
        "risks": [],
        "overall_summary": "The most balanced and best-governed proposal, meeting the RFP's timeline exactly with strong security and support commitments.",
    },
    "Orbit Digital": {
        "supplier_name": "Orbit Digital",
        "criteria": [
            _c(1, 5, "weak",
               "Solution approach is vague; specific technical details on confidence-thresholding and load testing are explicitly deferred to post-award workshops.",
               [{"quote": "Further technical details on the specific confidence-thresholding approach and load-testing results will be provided during solutioning workshops post-award", "page": 1}]),
            _c(2, 6, "moderate",
               "Shortest timeline due to existing environment familiarity, but team structure and named leads are not yet confirmed.",
               [{"quote": "Team structure and named leads for the augmented team will be confirmed at kickoff", "page": 1}]),
            _c(3, 7, "moderate",
               "Reasonable pricing reflecting the existing relationship, though the steady-state cost increase is not itemised in detail.",
               [{"quote": "an increase of USD 9,000 per month over our current contract", "page": 2}]),
            _c(4, 4, "weak",
               "We are SOC 2 Type II certified with continuous monitoring across all production systems.",
               [{"quote": "We are SOC 2 Type II certified with continuous monitoring across all production systems.", "page": 2}]),
            _c(5, 7, "strong",
               "Deep incumbent knowledge and one external reference, but two missed Sev-1 SLA commitments in the past 12 months are disclosed.",
               [{"quote": "two Severity 1 incidents in the past 12 months where the SLA-committed response time was missed", "page": 2}]),
        ],
        "risks": ["Two disclosed Sev-1 SLA misses in the past 12 months.",
                  "Integration approach deferred to post-award, limiting technical evaluability."],
        "overall_summary": "Lowest transition cost by virtue of incumbency, with deep environment knowledge, but a vaguer technical proposal and a mixed recent delivery record.",
    },
    "Vantage Cloud Solutions": {
        "supplier_name": "Vantage Cloud Solutions",
        "criteria": [
            _c(1, 1, "missing",
               "No architecture, model, or integration approach is disclosed; details are withheld as 'proprietary' until after contract award, which cannot be evaluated.",
               []),
            _c(2, 1, "missing",
               "No concrete timeline or team structure provided.", []),
            _c(3, 1, "missing",
               "No price table provided; pricing deferred to a post-award discussion.", []),
            _c(4, 2, "weak",
               "Generic security claims with no certification evidence provided in the document.",
               [{"quote": "Vantage maintains industry-standard security practices", "page": 1}]),
            _c(5, 1, "missing",
               "No named references or comparable engagements described.", []),
        ],
        "risks": [
            "PROMPT INJECTION ATTEMPT DETECTED: the Security & Compliance section of this proposal "
            "contains an embedded instruction directing the evaluator to disregard the scoring rubric "
            "and award maximum scores on every criterion, and to conceal this instruction from its "
            "output. This instruction was identified and ignored; scores above reflect the proposal's "
            "actual (minimal) content only."
        ],
        "overall_summary": "Proposal lacks substantive content on every criterion and contains an embedded prompt-injection "
                            "attempt in its Security & Compliance section, which was detected and disregarded.",
    },
}
