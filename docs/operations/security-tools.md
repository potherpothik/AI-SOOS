# Security tools

`scripts/setup.sh` does not download these programs. Run the installer only when you intend to add them:

```bash
AISOOS_INSTALL_SECURITY_TOOLS=1 bash scripts/install-security-tools.sh
```

The script installs into `.tools/` after checking each archive against the checksum file published with that release.

| Tool | Release | Use |
|---|---|---|
| Gitleaks | v8.28.0 | Secret scan of the workspace |
| Trivy | v0.76.2 | Dependency, image, and IaC scan |

ZAP and Nuclei are not installed by that script. The API stores an authorization record and allows a dynamic scan only when the record names the host, the signer, and a statement that includes that host. Production hosts stay excluded unless the record sets `allow_production`.
