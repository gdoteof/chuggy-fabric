# Where a pod is told to find a GitHub App key against where its pod puts one,
# and the App it mints as against the App whose key the host holds. The argument
# for each assertion is in forge-app-key.py's own header.
#
# The host's apps are handed over as JSON rather than restated here, for the
# reason tests/github-repository-transition.nix hands over the roster: the id a
# manifest writes and the id the host mints under are one value and cannot
# drift.
{ pkgs, apps }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-forge-app-key" {
  nativeBuildInputs = [ pkgs.kubectl python ];
  apps = builtins.toJSON apps;
  passAsFile = [ "apps" ];
} ''
  set -eu
  kubectl kustomize ${../cluster/apps} > rendered.yaml
  python3 ${./forge-app-key.py} "$appsPath" rendered.yaml
  touch "$out"
''
