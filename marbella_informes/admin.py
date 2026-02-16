from django.contrib import admin

from marbella_informes.models import AnnualDataset, AnnualReport

# Register your models here.
admin.site.register(AnnualReport)
admin.site.register(AnnualDataset)