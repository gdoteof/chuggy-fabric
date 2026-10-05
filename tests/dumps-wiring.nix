# The dumps directory a host creates against the one the cluster's dumps claim
# binds, read off the rendered manifests. The argument is in dumps-wiring.py's
# header.
#
# The host's path is handed over rather than restated here, so that the value
# the check compares is the one the tmpfiles rule is built from.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-dumps-wiring" {
  nativeBuildInputs = [ pkgs.kubectl python ];
} ''
  set -eu
  kubectl kustomize ${../cluster/apps} > rendered.yaml
  python3 ${./dumps-wiring.py} rendered.yaml \
    ${pkgs.lib.escapeShellArg host.config.chuggy.state.dumps.path}
  touch "$out"
''
