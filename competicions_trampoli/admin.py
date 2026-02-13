from django.contrib import admin

from competicions_trampoli.models_trampoli import CompeticioAparell
from .models import Competicio

# Register your models here.
admin.site.register(Competicio)

admin.site.register(CompeticioAparell)
