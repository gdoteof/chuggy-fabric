# Who reports an action against who verifies the report: the API's roster and
# its Secret volumes, the release pipeline's `report` task, and the Secrets
# the host makes for both. The argument for each assertion is in
# action-reporters.py's own header.
#
# The host's two scripts are handed over as they are built rather than their
# Secrets restated here, for the reason tests/forge-app-key.nix hands over the
# host's apps: the name a manifest mounts and the name the host synchronises
# are one value and cannot drift.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  cluster = import ./rendered-cluster.nix { inherit pkgs; };
  build = import ./rendered-build-system.nix { inherit pkgs; };
  script = unit: host.config.systemd.services.${unit}.serviceConfig.ExecStart;
in
pkgs.runCommand "chuggy-action-reporters" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./action-reporters.py} ${cluster}/cluster.yaml ${build} \
    ${script "chuggy-secrets-generate"} ${script "chuggy-secrets-sync"}
  touch "$out"
''
