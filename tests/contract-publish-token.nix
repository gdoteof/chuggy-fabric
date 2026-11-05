# The contract publish token the host mints against the Task that mounts it.
# The argument for each assertion is in contract-publish-token.py's header.
#
# The host's Apps and tokens are handed over as JSON rather than restated, for
# the reason tests/forge-app-key.nix gives of its own: the name a manifest reads
# and the name the host mints are one value and cannot drift.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-build-system.nix { inherit pkgs; };
  tokens = host.config.chuggy.githubAppTokens;
in
pkgs.runCommand "chuggy-contract-publish-token" {
  nativeBuildInputs = [ python ];
  host = builtins.toJSON { inherit (tokens) apps tokens; };
  passAsFile = [ "host" ];
} ''
  set -eu
  python3 ${./contract-publish-token.py} "$hostPath" ${rendered}
  touch "$out"
''
