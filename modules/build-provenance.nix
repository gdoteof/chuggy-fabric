{ config, pkgs, lib, ... }:

let
  cfg = config.chuggy.buildProvenance;
  configuredResultsPath = config.chuggy.state.buildResults.path;
  resultsPath = if configuredResultsPath == null
    then "/run/chuggy-build-results-unconfigured"
    else configuredResultsPath;
  recorder = pkgs.writeShellApplication {
    name = "chuggy-build-provenance";
    runtimeInputs = [ pkgs.coreutils pkgs.gawk pkgs.gnugrep pkgs.jq pkgs.kubectl ];
    text = builtins.readFile ../scripts/record-build-provenance;
  };
in
{
  options.chuggy.buildProvenance = {
    enable = lib.mkEnableOption "durable Shipwright BuildRun provenance recording";
    batchSize = lib.mkOption {
      type = lib.types.ints.positive;
      default = 100;
      description = "Maximum number of terminal BuildRuns recorded per timer activation.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = configuredResultsPath != null;
        message = ''
          chuggy.buildProvenance.enable is on but chuggy.state.buildResults.path is unset.
          Name durable storage for verified build provenance before enabling the recorder.
        '';
      }
    ];
    systemd.services.chuggy-build-provenance = {
      description = "Persist terminal Shipwright build provenance";
      after = [ "k3s.service" ];
      wants = [ "k3s.service" ];
      environment = {
        RESULTS_PATH = resultsPath;
        BATCH_SIZE = toString cfg.batchSize;
      };
      serviceConfig = {
        Type = "oneshot";
        ExecStart = lib.getExe recorder;
        User = "root";
      };
    };
    systemd.timers.chuggy-build-provenance = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "5m";
        OnUnitActiveSec = "5m";
        RandomizedDelaySec = "30s";
      };
    };
  };
}
