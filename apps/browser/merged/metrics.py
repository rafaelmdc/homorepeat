from decimal import Decimal, ROUND_HALF_UP


PURITY_QUANTUM = Decimal("0.0001")


def normalize_purity(value) -> str:
    return format(Decimal(str(value)).quantize(PURITY_QUANTUM, rounding=ROUND_HALF_UP), "f")


def _summary_label(values):
    normalized_values = [str(value) for value in values if str(value)]
    unique_values = sorted(set(normalized_values))
    if not unique_values:
        return "-"
    if len(unique_values) == 1:
        return unique_values[0]
    return ", ".join(unique_values)


def _coordinate_label(coordinates):
    ordered_coordinates = sorted(coordinates)
    if not ordered_coordinates:
        return "-"
    if len(ordered_coordinates) == 1:
        start, end = ordered_coordinates[0]
        return f"{start}-{end}"
    return ", ".join(f"{start}-{end}" for start, end in ordered_coordinates)


def _parse_positive_int(value: str):
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def _parse_float(value: str):
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _counter_summary(counter):
    return [
        {"label": label, "count": count}
        for label, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]
