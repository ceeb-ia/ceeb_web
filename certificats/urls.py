from django.urls import path

from .views import CertificatsUploadView, processar_pdfs

app_name = "certificats"

urlpatterns = [
    path("", CertificatsUploadView.as_view(), name="upload"),
    path("processar/", processar_pdfs, name="processar_pdfs"),
]
