from app.models import RiskLevel

# Calibrated-probability thresholds for the four spec categories. Must match
# ml/package.py RISK_THRESHOLDS (chosen from real outcomes on the 2023+ test set:
# critical ~40% of files got bug fixes, high ~29%, medium ~21%, low 2-10%).
THRESHOLDS: list[tuple[float, RiskLevel]] = [
    (0.35, RiskLevel.critical),
    (0.20, RiskLevel.high),
    (0.10, RiskLevel.medium),
]


def risk_level_for(score: float) -> RiskLevel:
    for threshold, level in THRESHOLDS:
        if score >= threshold:
            return level
    return RiskLevel.low
