ALLOWED_STATS_RANKS = ("phylum", "class", "order", "family", "genus", "species")

DEFAULT_UNSCOPED_RANK = "class"
DEFAULT_BRANCH_SCOPED_RANK = "species"
DEFAULT_TOP_N = 1000
MAX_TOP_N = 2000
DEFAULT_MIN_COUNT = 3


def normalize_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_residue(value) -> str:
    return normalize_text(value).upper()


def parse_non_negative_int(value):
    normalized = normalize_text(value)
    if not normalized:
        return None
    try:
        parsed = int(normalized)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def parse_float(value):
    normalized = normalize_text(value)
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def clamp_int(value: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def normalize_rank(value, *, branch_scope_active: bool) -> str:
    normalized = normalize_text(value).lower()
    if normalized in ALLOWED_STATS_RANKS:
        return normalized
    if branch_scope_active:
        return DEFAULT_BRANCH_SCOPED_RANK
    return DEFAULT_UNSCOPED_RANK


def next_lower_rank(current_rank: str) -> str:
    normalized = normalize_text(current_rank).lower()
    if normalized not in ALLOWED_STATS_RANKS:
        return DEFAULT_BRANCH_SCOPED_RANK

    current_index = ALLOWED_STATS_RANKS.index(normalized)
    if current_index >= len(ALLOWED_STATS_RANKS) - 1:
        return ALLOWED_STATS_RANKS[-1]
    return ALLOWED_STATS_RANKS[current_index + 1]


def normalize_top_n(value) -> int:
    parsed = parse_non_negative_int(value)
    if parsed is None:
        return DEFAULT_TOP_N
    return clamp_int(parsed, minimum=1, maximum=MAX_TOP_N)


def normalize_min_count(value) -> int:
    parsed = parse_non_negative_int(value)
    if parsed is None:
        return DEFAULT_MIN_COUNT
    return clamp_int(parsed, minimum=1)
