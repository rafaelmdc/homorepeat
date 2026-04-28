from __future__ import annotations


def _codon_usage_value(codon_usage, name: str):
    if isinstance(codon_usage, dict):
        return codon_usage.get(name)
    return getattr(codon_usage, name)


def format_repeat_pattern(amino_acid_sequence: str | None) -> str:
    """Return compact run-length architecture for an amino-acid repeat region."""
    sequence = (amino_acid_sequence or "").strip()
    if not sequence:
        return ""

    parts: list[str] = []
    current_residue = sequence[0]
    current_count = 1

    for residue in sequence[1:]:
        if residue == current_residue:
            current_count += 1
            continue
        parts.append(f"{current_count}{current_residue}")
        current_residue = residue
        current_count = 1

    parts.append(f"{current_count}{current_residue}")
    return "".join(parts)


def format_protein_position(start: int | None, end: int | None, protein_length: int | None) -> str:
    """Return compact protein coordinates, with midpoint percent when available."""
    if start is None or end is None:
        return ""

    coordinates = f"{start}-{end}"
    if not protein_length or protein_length <= 0:
        return coordinates

    midpoint = (start + end) / 2
    midpoint_percent = round((midpoint / protein_length) * 100)
    return f"{coordinates} ({midpoint_percent}%)"


def summarize_target_codon_usage(codon_usages, target_residue: str, target_count: int | None) -> dict[str, object]:
    target_residue = (target_residue or "").upper()
    rows = []
    for codon_usage in codon_usages:
        amino_acid = str(_codon_usage_value(codon_usage, "amino_acid") or "").upper()
        if amino_acid != target_residue:
            continue
        codon = str(_codon_usage_value(codon_usage, "codon") or "").upper()
        try:
            count = int(_codon_usage_value(codon_usage, "codon_count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            continue
        rows.append((codon, count))

    rows.sort(key=lambda row: (-row[1], row[0]))
    covered_count = sum(count for _, count in rows)
    denominator = int(target_count or 0)
    coverage = f"{covered_count}/{denominator}" if denominator > 0 else str(covered_count)

    if covered_count <= 0:
        return {
            "coverage": coverage,
            "profile": "",
            "counts": "",
            "dominant_codon": "",
            "parseable_counts": "",
            "parseable_fractions": "",
            "covered_count": 0,
            "target_count": denominator,
        }

    profile = ", ".join(
        f"{codon} {round((count / covered_count) * 100)}%"
        for codon, count in rows
    )
    counts = " / ".join(f"{codon} {count}" for codon, count in rows)
    parseable_counts = ";".join(f"{codon}={count}" for codon, count in rows)
    parseable_fractions = ";".join(
        f"{codon}={count / covered_count:.3f}"
        for codon, count in rows
    )
    return {
        "coverage": coverage,
        "profile": profile,
        "counts": counts,
        "dominant_codon": rows[0][0],
        "parseable_counts": parseable_counts,
        "parseable_fractions": parseable_fractions,
        "covered_count": covered_count,
        "target_count": denominator,
    }
