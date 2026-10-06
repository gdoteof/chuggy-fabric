{ pkgs, host, expectSecretRef ? null }:

let
  manifest = host.config.services.k3s.manifests.flux-sync.source;
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  # What the manifest is held to: the host's own options, and the credential
  # reference the caller states apart from them.
  expected = pkgs.writeText "flux-wiring-expected.json" (builtins.toJSON {
    inherit (host.config.chuggy.flux)
      repositoryUrl branch sourceInterval path interval timeout;
    secretRef = expectSecretRef;
  });
in
pkgs.runCommand "chuggy-flux-wiring" { nativeBuildInputs = [ python ]; } ''
  # The argument for each assertion is in flux-wiring.py's own header.
  python3 ${./flux-wiring.py} ${manifest} ${expected}
  touch "$out"
''
