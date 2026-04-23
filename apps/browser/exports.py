from dataclasses import dataclass
from typing import Callable

from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.http import StreamingHttpResponse
from django.utils.http import content_disposition_header


TSV_CONTENT_TYPE = "text/tab-separated-values; charset=utf-8"


@dataclass(frozen=True)
class TSVColumn:
    header: str
    value: str | Callable

    def get_value(self, obj):
        if callable(self.value):
            return self.value(obj)

        value = obj
        for attr in self.value.split("."):
            value = getattr(value, attr, None)
            if value is None:
                return None
        return value


def clean_tsv_value(value) -> str:
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)

    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _format_tsv_row(values) -> str:
    return "\t".join(clean_tsv_value(value) for value in values) + "\n"


def iter_tsv_rows(headers, rows):
    headers = tuple(headers)
    expected_width = len(headers)

    yield _format_tsv_row(headers)

    for row in rows:
        row = tuple(row)
        if len(row) != expected_width:
            raise ValueError(
                f"TSV row has {len(row)} cells but expected {expected_width}."
            )
        yield _format_tsv_row(row)


def stream_tsv_response(filename: str, headers, rows) -> StreamingHttpResponse:
    response = StreamingHttpResponse(
        iter_tsv_rows(headers, rows),
        content_type=TSV_CONTENT_TYPE,
    )
    response["Content-Disposition"] = content_disposition_header(
        as_attachment=True,
        filename=filename,
    )
    return response


class BrowserTSVExportMixin:
    download_param = "download"
    download_value = "tsv"
    download_strip_params = ("page", "after", "before", "fragment")
    tsv_chunk_size = 2000
    tsv_columns = ()
    tsv_filename_slug = ""
    download_tsv_label = "Download TSV"

    def dispatch(self, request, *args, **kwargs):
        if request.GET.get(self.download_param, "").strip() == self.download_value:
            return self.render_tsv_response()
        return super().dispatch(request, *args, **kwargs)

    def get_tsv_columns(self):
        return tuple(_normalize_tsv_column(column) for column in self.tsv_columns)

    def get_tsv_filename(self):
        slug = self.tsv_filename_slug or self.__class__.__name__.lower()
        return f"homorepeat_{slug}.tsv"

    def get_tsv_download_url(self):
        query = self.request.GET.copy()
        for param in self.download_strip_params:
            query.pop(param, None)
        query[self.download_param] = self.download_value
        encoded_query = query.urlencode()
        return f"{self.request.path}?{encoded_query}" if encoded_query else self.request.path

    def get_tsv_download_action(self):
        return {
            "href": self.get_tsv_download_url(),
            "label": self.download_tsv_label,
        }

    def get_tsv_queryset(self):
        return self.prepare_tsv_queryset(self.get_queryset())

    def prepare_tsv_queryset(self, queryset):
        return queryset

    def iter_tsv_data_rows(self):
        columns = self.get_tsv_columns()
        rows = self.get_tsv_queryset()
        if hasattr(rows, "iterator"):
            rows = rows.iterator(chunk_size=self.tsv_chunk_size)

        for obj in rows:
            yield [column.get_value(obj) for column in columns]

    def render_tsv_response(self):
        columns = self.get_tsv_columns()
        return stream_tsv_response(
            self.get_tsv_filename(),
            [column.header for column in columns],
            self.iter_tsv_data_rows(),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["download_tsv_url"] = self.get_tsv_download_url()
        context["download_tsv_action"] = self.get_tsv_download_action()
        return context


class StatsTSVExportMixin:
    download_param = "download"
    download_strip_params = ("page", "after", "before", "fragment")
    stats_tsv_dataset_keys = ()
    tsv_filename_slug = ""
    download_tsv_label = "Download TSV"

    def dispatch(self, request, *args, **kwargs):
        if self.get_requested_tsv_dataset_key():
            return self.render_stats_tsv_response()
        return super().dispatch(request, *args, **kwargs)

    def get_requested_tsv_dataset_key(self) -> str:
        return self.request.GET.get(self.download_param, "").strip()

    def get_stats_tsv_dataset_keys(self):
        return tuple(self.stats_tsv_dataset_keys)

    def get_tsv_download_url(self, dataset_key: str):
        query = self.request.GET.copy()
        for param in self.download_strip_params:
            query.pop(param, None)
        query[self.download_param] = dataset_key
        encoded_query = query.urlencode()
        return f"{self.request.path}?{encoded_query}" if encoded_query else self.request.path

    def get_tsv_download_action(self, dataset_key: str, *, label: str | None = None):
        return {
            "href": self.get_tsv_download_url(dataset_key),
            "label": label or self.download_tsv_label,
        }

    def get_tsv_download_actions(self, *definitions):
        actions = []
        for definition in definitions:
            if not definition.get("available", True):
                continue
            actions.append(
                self.get_tsv_download_action(
                    definition["dataset_key"],
                    label=definition.get("label"),
                )
            )
        return actions

    def get_stats_tsv_filename(self, dataset_key: str) -> str:
        slug = self.tsv_filename_slug or self.__class__.__name__.lower()
        return f"homorepeat_{slug}_{dataset_key}.tsv"

    def get_stats_tsv_headers(self, dataset_key: str):
        resolver = getattr(self, f"get_{self._dataset_method_token(dataset_key)}_tsv_headers", None)
        if resolver is None:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} must define TSV headers for dataset '{dataset_key}'."
            )
        return resolver()

    def iter_stats_tsv_rows(self, dataset_key: str):
        resolver = getattr(self, f"iter_{self._dataset_method_token(dataset_key)}_tsv_rows", None)
        if resolver is None:
            return ()
        return resolver()

    def is_stats_tsv_dataset_available(self, dataset_key: str) -> bool:
        resolver = getattr(self, f"is_{self._dataset_method_token(dataset_key)}_tsv_available", None)
        if resolver is None:
            return True
        return resolver()

    def render_stats_tsv_response(self):
        dataset_key = self.get_requested_tsv_dataset_key()
        if dataset_key not in self.get_stats_tsv_dataset_keys():
            raise Http404(f"Unknown TSV dataset '{dataset_key}'.")

        rows = (
            self.iter_stats_tsv_rows(dataset_key)
            if self.is_stats_tsv_dataset_available(dataset_key)
            else ()
        )
        return stream_tsv_response(
            self.get_stats_tsv_filename(dataset_key),
            self.get_stats_tsv_headers(dataset_key),
            rows,
        )

    def _dataset_method_token(self, dataset_key: str) -> str:
        return dataset_key.replace("-", "_")


def _normalize_tsv_column(column) -> TSVColumn:
    if isinstance(column, TSVColumn):
        return column

    header, value = column
    return TSVColumn(header, value)
