# Who may reach Hydra's and Kratos's admin ports, read off the rendered
# manifests rather than off the text that produces them: one NetworkPolicy
# element list in `ory`, Services that target container ports by name, and each
# caller's URL and egress arm in another namespace. The argument for each
# assertion is in ory-admin.py's own header.
{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-cluster.nix { inherit pkgs; };
in
pkgs.runCommand "chuggy-ory-admin" {
  nativeBuildInputs = [ python ];
} ''
  set -eu
  python3 ${./ory-admin.py} ${rendered}/cluster.yaml
  touch "$out"
''
