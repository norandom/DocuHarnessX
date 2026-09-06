# Compliance self-assessment

This matrix is a **self-assessment reference**, not a certification or auditor opinion.

<div class="dhx-layer" data-min="1" markdown="1">

| Pillar | iso27001 | nis2 | cra | gdpr |
|---|---|---|---|---|
| Asset & data inventory | <span class="dhx-fail">red</span> | <span class="dhx-fail">red</span> | <span class="dhx-fail">red</span> | <span class="dhx-fail">red</span> |
| Access control | <span class="dhx-fail">red</span> | <span class="dhx-fail">red</span> | <span class="dhx-na">n/a</span> | <span class="dhx-fail">red</span> |
| Cryptography | <span class="dhx-fail">red</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> | <span class="dhx-fail">red</span> |
| Logging & monitoring | <span class="dhx-pass">green</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> | <span class="dhx-pass">green</span> |
| Vulnerability management | <span class="dhx-fail">red</span> | <span class="dhx-na">n/a</span> | <span class="dhx-fail">red</span> | <span class="dhx-na">n/a</span> |
| Secure development | <span class="dhx-pass">green</span> | <span class="dhx-na">n/a</span> | <span class="dhx-pass">green</span> | <span class="dhx-pass">green</span> |
| Supply chain / SBOM | <span class="dhx-fail">red</span> | <span class="dhx-fail">red</span> | <span class="dhx-fail">red</span> | <span class="dhx-fail">red</span> |
| Incident response | <span class="dhx-pass">green</span> | <span class="dhx-pass">green</span> | <span class="dhx-pass">green</span> | <span class="dhx-pass">green</span> |
| Backup & continuity | <span class="dhx-fail">red</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> |
| Privacy & data-subject rights | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> | <span class="dhx-fail">red</span> |
| Cardholder data environment | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> |
| Policies & governance docs | <span class="dhx-pass">green</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> | <span class="dhx-pass">green</span> |
| Awareness / training | <span class="dhx-fail">red</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> | <span class="dhx-na">n/a</span> |

</div>

<div class="dhx-layer" data-min="5" markdown="1">

## Evidence

- **iso27001 / Logging & monitoring** pass: `docuharnessx/ontology/schema.py`, `tests/ontology/test_errors.py`, `tests/ontology/test_hardening.py`, `tests/ontology/test_model.py`, `tests/ontology/test_normalize_prefix.py`, `tests/ontology/test_package_import.py`
- **gdpr / Logging & monitoring** pass: `docuharnessx/ontology/schema.py`, `tests/ontology/test_errors.py`, `tests/ontology/test_hardening.py`, `tests/ontology/test_model.py`, `tests/ontology/test_normalize_prefix.py`, `tests/ontology/test_package_import.py`
- **iso27001 / Secure development** pass: `.github/workflows/adopt.yml`, `.github/workflows/dhx.yml`, `.github/workflows/docs.yml`, `tests/fixtures/agentic_repo/README.md`, `tests`, `tests/ontology/test_errors.py`
- **cra / Secure development** pass: `.github/workflows/adopt.yml`, `.github/workflows/dhx.yml`, `.github/workflows/docs.yml`, `tests/fixtures/agentic_repo/README.md`, `tests`, `tests/ontology/test_errors.py`
- **gdpr / Secure development** pass: `.github/workflows/adopt.yml`, `.github/workflows/dhx.yml`, `.github/workflows/docs.yml`, `tests/fixtures/agentic_repo/README.md`, `tests`, `tests/ontology/test_errors.py`
- **iso27001 / Incident response** pass: `.kiro/settings/templates/steering-custom/security.md`
- **nis2 / Incident response** pass: `.kiro/settings/templates/steering-custom/security.md`
- **cra / Incident response** pass: `.kiro/settings/templates/steering-custom/security.md`
- **gdpr / Incident response** pass: `.kiro/settings/templates/steering-custom/security.md`
- **iso27001 / Policies & governance docs** pass: `.kiro/settings/templates/steering-custom/security.md`, `tests/test_ci_policy.py`
- **gdpr / Policies & governance docs** pass: `.kiro/settings/templates/steering-custom/security.md`, `tests/test_ci_policy.py`

</div>

