"""Transparent deterministic weights for simulation-only derived features.

These are not prediction-model outputs. They create reusable baseline features
for the Scenario Simulation layer. Target-role/target-department fit is still
calculated later by the relevant scenario engine.
"""

FEATURE_VERSION = "1.0"

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
