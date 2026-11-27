# Gateway-only immutable Python base review (2026-11-27)

**Review only / no production release approval.** The current Dockerfile.gateway parent was pinned to `python:3.11-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535`. The four-image Artifact Scanning matrix previously overrode every Dockerfile base with that same immutable Trixie parent; simply editing one Dockerfile would not cause CI to test it.

This candidate selects the official Python 3.11 slim **Bookworm** index digest
`python:3.11-slim-bookworm@sha256:ef56ae98435cc40d8a27020b0b32a9941515acd5840f0fba34858bb34dd362d1` for the gateway only. The scan workflow continues to build the other three images from the original Trixie digest, with Trivy, Grype, image-integrity checks, and Python-package checks unchanged.

## Evidence and rationale

- Debian Security Tracker, CVE-2026-76642: Debian 12 Bookworm `util-linux 2.38.1` is **not affected**, while Trixie `2.41.5-0+deb13u1` is vulnerable. https://security-tracker.debian.org/tracker/CVE-2026-76642
- Debian Security Tracker, CVE-2025-69720: **both Bookworm and Trixie remain affected** by the ncurses issue; this candidate is **not** a CVE-free base or a release gate waiver. https://security-tracker.debian.org/tracker/CVE-2025-69720
- Official Python 3.11 Docker image is published with `3.11-slim-bookworm` and a manifest-index digest reported by Docker Hub. https://hub.docker.com/layers/library/python/3.11-slim-bookworm/images/sha256-66b43a225b4cf4b4393d31243c08a2f9c35e8218746d4a3c2682b1936a87afda
- Review exact Docker Hub digest and architecture mapping before approval; candidate's previous source images remain available for rollback.

## Required checks before any merge or deploy

- [ ] Build exact commit in ephemeral CI and verify that scan-target OCI config/manifest digest matches the actual locally scanned image.
- [ ] Inspect the gateway's **full** Trivy and Grype findings, compare package versions and severity to the original Trixie image, not just the aggregate count.
- [ ] Run synthetic authentication, disabled/deleted JWT rejection, broker-reader **read-only** tests and general CI on exactly this commit.
- [ ] Prove the gateway image starts with its persistent auth DB mount and does not attempt to create or accept an ephemeral account authority.
- [ ] Record package-lock/constraints compatibility (including OpenSSL, libc, Python wheel ABI, setuptools), complete SBOM and fix or document all remaining HIGH/CRITICAL findings.
- [ ] Independent security/release review and explicit approval. Do not deploy, switch trading orders, change payments, disable scanners or bypass protected release pins.

This candidate affects the public gateway image only. It does not modify the protected Kraken release source, keys, order gate, or existing customer data.
