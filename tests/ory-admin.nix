# Who may reach Hydra's and Kratos's admin ports, read off the rendered
# manifests rather than off the text that produces them: one NetworkPolicy
# element list in `ory`, Services that target container ports by name, and each
# caller's URL and egress arm in another namespace. The argument for each
# assertion is in ory-admin.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
in
pkgs.runCommand "chuggy-ory-admin" {
  nativeBuildInputs = [ pkgs.kubectl python ];
} ''
  set -eu
  kubectl kustomize ${../cluster/apps} > rendered.yaml
  python3 ${./ory-admin.py} rendered.yaml
  touch "$out"
''
