"""OpenTelemetry helpers with a deliberately small, sanitized attribute vocabulary."""

from opentelemetry import trace

TRACER = trace.get_tracer("claimtriagelab", "0.1.0")


def set_common_attributes(span, *, correlation_id: str, operation: str) -> None:
    span.set_attribute("claimtriagelab.correlation_id", correlation_id)
    span.set_attribute("claimtriagelab.operation", operation)
