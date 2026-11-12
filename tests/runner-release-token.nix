# The runner release tokens the host mints against the Task that mounts them.
# The argument for each assertion is in runner-release-token.py's header.
#
# The host's Apps and tokens are handed over as JSON, as
# contract-publish-token.nix hands them over.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  rendered = import ./rendered-build-system.nix { inherit pkgs; };
  tokens = host.config.chuggy.githubAppTokens;
in
pkgs.runCommand "chuggy-runner-release-token" {
  nativeBuildInputs = [ python ];
  host = builtins.toJSON { inherit (tokens) apps tokens; };
  passAsFile = [ "host" ];
} ''
  set -eu
  python3 ${./runner-release-token.py} "$hostPath" ${rendered}
  touch "$out"
''
