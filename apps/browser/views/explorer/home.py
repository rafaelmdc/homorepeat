from django.views.generic import TemplateView

from ..navigation import _browser_directory_sections
from ..querysets import _summary_runs


class BrowserHomeView(TemplateView):
    template_name = "browser/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["directory_sections"] = _browser_directory_sections()
        context["recent_runs"] = _summary_runs()[:5]
        return context
