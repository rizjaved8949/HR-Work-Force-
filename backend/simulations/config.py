"""Transparent deterministic weights for the Scenario Simulation layer.

No value here is a prediction-model output. These constants make the simulation
calculations explicit, testable, and easy for HR/business owners to review.
"""

FEATURE_VERSION = "1.0"
SIMULATION_ENGINE_VERSION = "2.0"

MOBILITY_SCORE = {
    "Ready Now": 100.0,
    "Ready in 6-12 Months": 75.0,
    "Development Required": 40.0,
    "Not Ready": 10.0,
}

ELIGIBILITY_SCORE = {
    "Eligible": 100.0,
    "Development / Hold": 50.0,
    "Not Yet Eligible": 35.0,
    "Not Eligible": 0.0,
}

PROMOTION_BASE_WEIGHTS = {
    "performance": 0.35,
    "experience": 0.25,
    "attendance": 0.15,
    "mobility": 0.15,
    "eligibility": 0.10,
}

TRANSFER_BASE_WEIGHTS = {
    "performance": 0.25,
    "attendance": 0.20,
    "mobility": 0.25,
    "cross_functional_exposure": 0.20,
    "eligibility": 0.10,
}

RESKILLING_BASE_WEIGHTS = {
    "performance": 0.20,
    "attendance": 0.15,
    "engagement": 0.20,
    "learning_activity": 0.25,
    "mobility": 0.20,
}

JOB_LEVEL_ORDER = {
    "Intern": 0,
    "Junior": 1,
    "Mid": 2,
    "Senior": 3,
    "Lead/Manager": 4,
    "Executive": 5,
}

PROMOTION_FINAL_WEIGHTS = {
    "base_readiness": 0.60,
    "target_skill_match": 0.30,
    "mandatory_skill_coverage": 0.10,
}

READINESS_BANDS = (
    (85.0, "ready_now"),
    (70.0, "ready_with_minor_gaps"),
    (55.0, "development_required"),
    (0.0, "not_ready"),
)
