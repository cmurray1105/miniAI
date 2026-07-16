"""OpenTelemetry setup for miniAI's service request path.

Telemetry is disabled unless OTEL_EXPORTER_OTLP_ENDPOINT is configured. This
keeps local unit tests and ad-hoc development free of an external dependency.
"""
from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(app) -> None:
    """Export traces when an OTLP endpoint is configured; otherwise use no-op API."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    resource = Resource.create({
        SERVICE_NAME: "miniai-gateway",
        SERVICE_VERSION: os.getenv("DEPLOYMENT_VERSION", "dev"),
        "deployment.environment.name": os.getenv("DEPLOYMENT_ENVIRONMENT", "local"),
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=endpoint, insecure=True)
    ))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    RequestsInstrumentor().instrument(tracer_provider=provider)
