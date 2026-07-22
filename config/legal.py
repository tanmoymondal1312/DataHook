"""Public legal pages.

`/privacy/` is the URL handed to the Play Console, so it must stay reachable
without authentication and must not require the API to be up.
"""

from django.conf import settings
from django.views.generic import TemplateView


class PrivacyPolicyView(TemplateView):
    template_name = "legal/privacy.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            contact_email=settings.PRIVACY_CONTACT_EMAIL,
            updated=settings.PRIVACY_POLICY_UPDATED,
            base_url=settings.BASE_URL,
        )
        return context
