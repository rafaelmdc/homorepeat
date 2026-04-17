from django.urls import path

from .views import (
    AccessionDetailView,
    AccessionCallCountListView,
    AccessionStatusListView,
    AccessionsListView,
    BrowserHomeView,
    CodonRatioExplorerView,
    DownloadManifestEntryListView,
    GenomeDetailView,
    GenomeListView,
    NormalizationWarningListView,
    ProteinDetailView,
    ProteinListView,
    RepeatLengthExplorerView,
    RepeatCallDetailView,
    RepeatCallListView,
    RunDetailView,
    RunListView,
    SequenceDetailView,
    SequenceListView,
    TaxonDetailView,
    TaxonListView,
)


app_name = "browser"

urlpatterns = [
    path("", BrowserHomeView.as_view(), name="home"),
    path("accessions/", AccessionsListView.as_view(), name="accession-list"),
    path("accessions/<path:accession>/", AccessionDetailView.as_view(), name="accession-detail"),
    path("accession-call-counts/", AccessionCallCountListView.as_view(), name="accessioncallcount-list"),
    path("accession-status/", AccessionStatusListView.as_view(), name="accessionstatus-list"),
    path("download-manifest/", DownloadManifestEntryListView.as_view(), name="downloadmanifest-list"),
    path("runs/", RunListView.as_view(), name="run-list"),
    path("runs/<int:pk>/", RunDetailView.as_view(), name="run-detail"),
    path("lengths/", RepeatLengthExplorerView.as_view(), name="lengths"),
    path("codon-ratios/", CodonRatioExplorerView.as_view(), name="codon-ratios"),
    path("taxa/", TaxonListView.as_view(), name="taxon-list"),
    path("taxa/<int:pk>/", TaxonDetailView.as_view(), name="taxon-detail"),
    path("genomes/", GenomeListView.as_view(), name="genome-list"),
    path("genomes/<int:pk>/", GenomeDetailView.as_view(), name="genome-detail"),
    path("sequences/", SequenceListView.as_view(), name="sequence-list"),
    path("sequences/<int:pk>/", SequenceDetailView.as_view(), name="sequence-detail"),
    path("proteins/", ProteinListView.as_view(), name="protein-list"),
    path("proteins/<int:pk>/", ProteinDetailView.as_view(), name="protein-detail"),
    path("calls/", RepeatCallListView.as_view(), name="repeatcall-list"),
    path("calls/<int:pk>/", RepeatCallDetailView.as_view(), name="repeatcall-detail"),
    path("warnings/", NormalizationWarningListView.as_view(), name="normalizationwarning-list"),
]
