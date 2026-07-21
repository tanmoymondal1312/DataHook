"""Admin registration for endpoints, attributes and submissions."""

from django.contrib import admin

from .models import Attribute, Endpoint, Submission


class AttributeInline(admin.TabularInline):
    model = Attribute
    extra = 1


@admin.register(Endpoint)
class EndpointAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "owner", "notify_on_submit", "created_at"]
    search_fields = ["name", "slug", "owner__email"]
    readonly_fields = ["slug", "api_key", "created_at"]
    inlines = [AttributeInline]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["id", "endpoint", "source_ip", "created_at"]
    search_fields = ["endpoint__slug"]
    list_filter = ["endpoint"]
    readonly_fields = ["endpoint", "data", "source_ip", "created_at"]
