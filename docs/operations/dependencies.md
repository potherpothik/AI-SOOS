# Recorded from `pip check` on the development environment. The pins in
# pyproject.toml were not changed. `requirements.lock` reproduces the set that
# actually installed, including this conflict. The application tests pass
# against that set.

```
opentelemetry-sdk 1.37.0 has requirement opentelemetry-api==1.37.0, but you have opentelemetry-api 1.45.2.
semgrep 1.184.0 has requirement mcp==1.29.0, but you have mcp 2.3.0.
semgrep 1.184.0 has requirement opentelemetry-api~=1.37.0, but you have opentelemetry-api 1.45.2.
opentelemetry-semantic-conventions 0.58b0 has requirement opentelemetry-api==1.37.0, but you have opentelemetry-api 1.45.2.
```

`headroom-ai` brings in the newer OpenTelemetry API and `mcp` 2.x. Semgrep and the pinned OpenTelemetry SDK still import. Do not force a silent downgrade until a lockfile can satisfy every declared requirement at once.
