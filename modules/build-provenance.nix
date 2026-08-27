{ config, pkgs, lib, ... }:

let
  cfg = config.chuggy.buildProvenance;
  configuredResultsPath = config.chuggy.state.buildResults.path;
  resultsPath = if configuredResultsPath == null
    then "/run/chuggy-build-results-unconfigured"
    else configuredResultsPath;
  recorder = pkgs.writeShellApplication {
    name = "chuggy-build-provenance";
    runtimeInputs = [ pkgs.coreutils pkgs.diffutils pkgs.gawk pkgs.gnugrep pkgs.jq pkgs.kubectl ];
    text = builtins.readFile ../scripts/record-build-provenance;
  };
  observer = pkgs.writeShellApplication {
    name = "chuggy-build-attempt-alerts";
    runtimeInputs = [ pkgs.coreutils pkgs.jq pkgs.kubectl ];
    text = builtins.readFile ../scripts/check-build-attempts;
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
    stalledAfterSeconds = lib.mkOption {
      type = lib.types.ints.positive;
      default = 4500;
      description = "Age at which a non-terminal BuildRun is reported as stalled.";
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
    systemd.services.chuggy-build-attempt-alerts = {
      description = "Report failed and stalled Shipwright build attempts";
      after = [ "k3s.service" ];
      wants = [ "k3s.service" ];
      environment = {
        BATCH_SIZE = toString cfg.batchSize;
        STALLED_AFTER_SECONDS = toString cfg.stalledAfterSeconds;
      };
      serviceConfig = {
        Type = "oneshot";
        ExecStart = lib.getExe observer;
        User = "root";
      };
    };
    systemd.timers.chuggy-build-attempt-alerts = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2m";
        OnUnitActiveSec = "2m";
        RandomizedDelaySec = "15s";
      };
    };
  };
}
