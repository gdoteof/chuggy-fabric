# The layers a host's root Kustomization applies, read off the rendered
# directory its `chuggy.flux.path` names rather than off the files in it.
#
# The directory is taken from the host so that the path the host generates and
# the declarations this holds cannot come apart: a default that moved would
# render some other directory here, which this refuses. The argument for each
# assertion is in flux-layers.py's own header.
{ pkgs, host }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  layers = ../. + "/${host.config.chuggy.flux.path}";
in
pkgs.runCommand "chuggy-flux-layers" {
  nativeBuildInputs = [ pkgs.kubectl python ];
} ''
  set -eu
  kubectl kustomize ${layers} > rendered.yaml
  python3 ${./flux-layers.py} rendered.yaml
  touch "$out"
''
