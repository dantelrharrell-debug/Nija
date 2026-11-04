#!/usr/bin/env bash
set -euo pipefail

version="0.70.0"
archive="trivy_${version}_Linux-64bit.tar.gz"
expected_sha256="8b4376d5d6befe5c24d503f10ff136d9e0c49f9127a4279fd110b727929a5aa9"
install_root="${RUNNER_TEMP:?RUNNER_TEMP must be set}/nija-trivy-${version}"
binary_dir="${RUNNER_TEMP}/nija-trivy-bin"
archive_path="${install_root}/${archive}"
release_url="https://github.com/aquasecurity/trivy/releases/download/v${version}/${archive}"

mkdir -p "${install_root}" "${binary_dir}"
curl --fail --silent --show-error --location --retry 3 --retry-all-errors \
    --connect-timeout 15 --max-time 120 "${release_url}" --output "${archive_path}"
printf '%s  %s\n' "${expected_sha256}" "${archive}" \
    | (cd "${install_root}" && sha256sum --check --status)
tar --no-same-owner -xzf "${archive_path}" -C "${install_root}" trivy
install -m 0755 "${install_root}/trivy" "${binary_dir}/trivy"
echo "${binary_dir}" >> "${GITHUB_PATH:?GITHUB_PATH must be set}"
"${binary_dir}/trivy" --version
