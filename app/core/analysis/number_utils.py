def percent(numerator: float, denominator: float) -> float:
    return (numerator / denominator) * 100


def round_metric(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


def range_position(value: float, minimum: float | None, maximum: float | None) -> float | None:
    if minimum is None or maximum is None or maximum <= minimum:
        return None
    return percent(value - minimum, maximum - minimum)
