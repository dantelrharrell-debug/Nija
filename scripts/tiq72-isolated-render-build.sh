#!/usr/bin/env bash
# Existing isolated TIQ72 Build Command. Delegate dependency installation to
# the strict reviewed installer, rather than maintaining a less-protected copy.
# This never contacts payment providers, migrates data or enables paid routes.
set -euo pipefail

if [[ "${TIQ72_ISOLATED_BUILD_SCOPE:-}" != "holding-test-only" ]]; then
  echo "TIQ72_BUILD blocked: isolated_build_scope_missing" >&2
  exit 64
fi

# Render's build-time service identity must be present and exact; an absent
# identity is not evidence of the intended isolated TEST workspace.
if [[ "${RENDER_SERVICE_ID:-}" != "srv-dbqeqgqfngtc73fcphhg" ]]; then
  echo "TIQ72_BUILD blocked: wrong_or_missing_render_service" >&2
  exit 64
fi

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
installer="$root/scripts/tiq72_install_isolated_dependencies.sh"
if [[ ! -s "$installer" ]]; then
  echo "TIQ72_BUILD blocked: reviewed_installer_missing" >&2
  exit 65
fi

# The delegated installer checks the exact Render service ID and the complete
# approved Node/Python dependency allowlist, then installs and audits them.
sh "$installer"
echo "TIQ72_BUILD verified: strict_pinned_node_and_python_dependencies_installed"
