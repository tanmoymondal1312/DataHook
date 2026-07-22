"""Serializers for endpoints, attributes and submissions."""

from rest_framework import serializers

from .models import Attribute, Endpoint, Submission
from .snippets import build_snippets
from .validators import validate_attribute_key


class AttributeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attribute
        fields = [
            "id", "label", "key", "type", "required", "order",
            "show_in_notification",
        ]

    def validate_key(self, value):
        value = (value or "").strip()
        # Enforce the strict no-space slug rule (raises 400 on failure).
        validate_attribute_key(value)
        return value

    def validate(self, attrs):
        """Ensure the key is unique within the endpoint."""
        endpoint = self.context.get("endpoint")
        # On update, fall back to the instance's endpoint.
        if endpoint is None and self.instance is not None:
            endpoint = self.instance.endpoint

        key = attrs.get("key", getattr(self.instance, "key", None))
        if endpoint is not None and key is not None:
            qs = Attribute.objects.filter(endpoint=endpoint, key=key)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"key": "An attribute with this key already exists "
                            "for this endpoint."}
                )
        return attrs


class EndpointListSerializer(serializers.ModelSerializer):
    """Compact endpoint representation for the list view."""

    submission_count = serializers.IntegerField(read_only=True)
    attribute_count = serializers.IntegerField(read_only=True)
    ingest_url = serializers.CharField(read_only=True)

    class Meta:
        model = Endpoint
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "notify_on_submit",
            "notify_title",
            "ingest_url",
            "submission_count",
            "attribute_count",
            "created_at",
        ]


class EndpointWriteSerializer(serializers.ModelSerializer):
    """Create/update payload — only owner-editable fields are writable."""

    class Meta:
        model = Endpoint
        fields = [
            "id", "name", "description", "notify_on_submit", "notify_title",
        ]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value


class EndpointDetailSerializer(serializers.ModelSerializer):
    """Full endpoint detail: attributes, ingest URL, api key and snippets."""

    attributes = AttributeSerializer(many=True, read_only=True)
    ingest_url = serializers.CharField(read_only=True)
    snippets = serializers.SerializerMethodField()
    submission_count = serializers.SerializerMethodField()
    attribute_count = serializers.SerializerMethodField()

    class Meta:
        model = Endpoint
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "notify_on_submit",
            "notify_title",
            "api_key",
            "ingest_url",
            "attributes",
            "snippets",
            "submission_count",
            "attribute_count",
            "created_at",
        ]

    def get_snippets(self, obj):
        attributes = obj.attributes.all()
        return build_snippets(obj, attributes)

    def get_submission_count(self, obj):
        return obj.submissions.count()

    def get_attribute_count(self, obj):
        return obj.attributes.count()


class SubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Submission
        fields = ["id", "data", "source_ip", "created_at"]
        read_only_fields = fields


class AggregateSubmissionSerializer(serializers.ModelSerializer):
    """Submission item for the cross-endpoint feed (carries endpoint identity)."""

    endpoint_id = serializers.IntegerField(source="endpoint.id", read_only=True)
    endpoint_name = serializers.CharField(source="endpoint.name", read_only=True)

    class Meta:
        model = Submission
        fields = ["id", "endpoint_id", "endpoint_name", "data", "created_at"]
        read_only_fields = fields
