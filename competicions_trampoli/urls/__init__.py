from .base import urlpatterns as base_urlpatterns
from .classificacions import urlpatterns as classificacions_urlpatterns
from .inscripcions import urlpatterns as inscripcions_urlpatterns
from .judge import urlpatterns as judge_urlpatterns
from .rotacions import urlpatterns as rotacions_urlpatterns
from .scoring import urlpatterns as scoring_urlpatterns

urlpatterns = [
    *base_urlpatterns,
    *inscripcions_urlpatterns,
    *scoring_urlpatterns,
    *rotacions_urlpatterns,
    *classificacions_urlpatterns,
    *judge_urlpatterns,
]