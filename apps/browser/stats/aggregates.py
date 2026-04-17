from django.db.models import Aggregate, FloatField


class PercentileCont(Aggregate):
    function = "PERCENTILE_CONT"
    output_field = FloatField()
    allow_distinct = False
    template = "%(function)s(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"

    def __init__(self, percentile: float, expression, **extra):
        super().__init__(expression, percentile=str(float(percentile)), **extra)
