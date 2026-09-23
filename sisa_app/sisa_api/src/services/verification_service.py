from decimal import Decimal

from ..models.openstat import OpenStatObservation, VerificationStatus

_FLOAT_EPSILON = 1e-9


def rounding_tolerance(claimed_value: float) -> float:
    exponent = Decimal(repr(claimed_value)).normalize().as_tuple().exponent
    decimals = max(0, -int(exponent))
    return 0.5 * 10**-decimals


def compare(claimed_value: float, official: OpenStatObservation) -> tuple[VerificationStatus, str]:
    unit = "%" if official.unit == "percent" else f" {official.unit or ''}".rstrip()
    claimed = f"{claimed_value:g}{unit}"
    reported = f"{official.value:g}{unit}"
    period = f" for {official.period}" if official.period else ""
    difference = abs(official.value - claimed_value)

    if difference <= rounding_tolerance(claimed_value) + _FLOAT_EPSILON:
        return (
            "SUPPORTED",
            f"The claimed value ({claimed}) is consistent with the value reported by the selected "
            f"PSA OpenSTAT source ({reported}{period}) at the precision stated in the claim.",
        )

    points = "percentage points" if official.unit == "percent" else "units"
    return (
        "CONTRADICTED",
        f"The numerical value in the claim ({claimed}) differs from the value reported by the "
        f"selected PSA OpenSTAT source ({reported}{period}) by {difference:.3g} {points}.",
    )
