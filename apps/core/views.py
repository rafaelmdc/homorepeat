from django.http import JsonResponse
from django.views.generic import TemplateView


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sections"] = [
            {
                "title": "Browser",
                "description": "Run-first browsing for taxa, genomes, proteins, and repeat calls.",
                "url_name": "browser:home",
            },
            {
                "title": "Imports",
                "description": "Staff-facing run import tooling built around published TSV contracts.",
                "url_name": "imports:home",
            },
        ]
        return context


def healthcheck(_request):
    return JsonResponse({"status": "ok", "app": "homorepeat-web"})
