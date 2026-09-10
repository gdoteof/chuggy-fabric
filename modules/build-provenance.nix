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
  publisher = pkgs.writeShellApplication {
    name = "chuggy-build-results-publish";
    runtimeInputs = [ pkgs.coreutils pkgs.diffutils pkgs.gawk pkgs.git pkgs.jq pkgs.kubectl ];
    text = builtins.readFile ../scripts/publish-build-results;
  };
  # The delivery this host already declares for the token the push uses, so
  # neither the Secret's name nor the namespace it lands in is written twice.
  # `null` covers every way of not having one -- unnamed, or named and not
  # minted -- and the assertions below are what tell those apart for a reader.
  publishToken =
    if cfg.publish.tokenName == null
    then null
    else config.chuggy.githubAppTokens.tokens.${cfg.publish.tokenName} or null;
  fluxRepositoryUrl =
    if config.chuggy.flux.repositoryUrl == null then "" else config.chuggy.flux.repositoryUrl;
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

    # Where a verified result has to be for anything but this box to use one.
    # `scripts/render-image-promotion` takes a checksummed record and a
    # checkout, and the pod that runs it has the checkout and no path to this
    # host's disk.
    publish = {
      enable = lib.mkEnableOption "publishing recorded build results into the fabric repository";

      tokenName = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "finalizer-chuggy-fabric";
        description = ''
          Which entry of chuggy.githubAppTokens.tokens the push authenticates
          as. The Secret's name and its namespace are read from that entry, so
          renaming either there follows here rather than diverging.

          It has to be a write token for the repository chuggy.flux follows,
          and it has to be the portal App's: that branch's ruleset admits the
          portal App and repository admins, and the worker token this host also
          mints is exactly what such a ruleset exists to refuse.
        '';
      };

      authorName = lib.mkOption {
        type = lib.types.str;
        default = "chuggy-fabric build results";
        description = ''
          Author and committer of a publication. Fixed, because these commits
          are made by a timer and not by anyone: a name that resolved to a
          person would attribute a machine's copy to them.
        '';
      };

      authorEmail = lib.mkOption {
        type = lib.types.str;
        default = "noreply@invalid";
        description = ''
          Address on those commits. Reserved by RFC 2606 by default, which is
          the honest form of an address nothing reads -- the same domain
          scripts/render-image-promotion signs a promotion under.
        '';
      };
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
      {
        assertion = !cfg.publish.enable || cfg.publish.tokenName != null;
        message = ''
          chuggy.buildProvenance.publish.enable is on but
          chuggy.buildProvenance.publish.tokenName is unset. Name the GitHub App
          token the push authenticates as; there is no default that would not be
          a guess at which repository this host is allowed to write.
        '';
      }
      {
        assertion = !cfg.publish.enable || cfg.publish.tokenName == null || publishToken != null;
        message = ''
          chuggy.githubAppTokens does not mint the token
          chuggy.buildProvenance.publish.tokenName names. Declare it there, or
          name one of the entries repositories.nix already produces.
        '';
      }
      {
        assertion = !cfg.publish.enable || publishToken == null || publishToken.permission == "write";
        message = ''
          chuggy.buildProvenance.publish.tokenName names a read token. A
          publication is a push to the branch Flux follows.
        '';
      }
      {
        assertion = !cfg.publish.enable || publishToken == null
          || lib.length publishToken.namespaces == 1;
        message = ''
          chuggy.buildProvenance.publish.tokenName names a token delivered to
          more than one namespace, so which Secret the publisher reads would be
          a guess.
        '';
      }
      {
        assertion = !cfg.publish.enable || config.chuggy.flux.repositoryUrl != null;
        message = ''
          chuggy.buildProvenance.publish.enable is on but chuggy.flux.repositoryUrl
          is unset. The publication goes to the repository this host follows;
          there is no second answer to publish to.
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
    systemd.services.chuggy-build-results-publish = lib.mkIf cfg.publish.enable {
      description = "Publish recorded build provenance into the fabric repository";
      # Ordered after the recorder rather than triggered by it: a record is
      # briefly a JSON file without its checksum, and that ordering is what
      # keeps the common activation from reading the pair mid-rename. A record
      # missed either way is published by the next activation.
      after = [ "chuggy-build-provenance.service" "network-online.target" "k3s.service" ];
      wants = [ "network-online.target" "k3s.service" ];
      environment = {
        RESULTS_PATH = resultsPath;
        REPOSITORY_URL = fluxRepositoryUrl;
        BRANCH = config.chuggy.flux.branch;
        TOKEN_SECRET = if publishToken == null then "" else publishToken.secretName;
        TOKEN_NAMESPACE = if publishToken == null then "" else lib.head publishToken.namespaces;
        AUTHOR_NAME = cfg.publish.authorName;
        AUTHOR_EMAIL = cfg.publish.authorEmail;
      };
      serviceConfig = {
        Type = "oneshot";
        ExecStart = lib.getExe publisher;
        User = "root";
        # The clone is a cache of a branch that exists elsewhere, so it is a
        # StateDirectory rather than one of chuggy.state's paths: losing it
        # costs the next activation a clone and nothing else, and it needs none
        # of the backup treatment the records themselves need.
        StateDirectory = "chuggy-build-results-publish";
        StateDirectoryMode = "0700";
        RuntimeDirectory = "chuggy-build-results-publish";
        RuntimeDirectoryMode = "0700";
      };
    };
    systemd.timers.chuggy-build-results-publish = lib.mkIf cfg.publish.enable {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "7m";
        OnUnitActiveSec = "5m";
        RandomizedDelaySec = "30s";
      };
    };
  };
}
