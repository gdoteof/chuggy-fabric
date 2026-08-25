{ config, lib, ... }:

let
  cfg = config.chuggy.mini;
in
{
  options.chuggy.mini.enable = lib.mkEnableOption ''
    the self-contained single-node Chuggy role, including durable state,
    workload execution, image storage, build provenance, and a co-located builder
  '';

  config = lib.mkIf cfg.enable {
    chuggy.k3s = {
      enable = true;
      nodeLabels = [
        "chuggy.dev/durable=true"
        "chuggy.dev/pool=work"
        "chuggy.dev/node-role=builder"
      ];
    };
    chuggy.state.enable = true;
    chuggy.secrets.enable = true;
    chuggy.images.enable = true;
    chuggy.work.enable = true;
    chuggy.buildProvenance.enable = true;
    chuggy.flux.enable = true;

    assertions = [{
      assertion = !lib.elem "chuggy.dev/node-role=builder:NoSchedule" config.chuggy.k3s.nodeTaints;
      message = "chuggy.mini cannot taint its only node as a dedicated builder";
    }];
  };
}
