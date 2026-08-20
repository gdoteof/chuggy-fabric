{ config, pkgs, lib, ... }:

{
  # ---------------------------------------------------------------- boot ----

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  # The ESP is 511 MB and each generation costs ~37 MB of initrd. Without a cap
  # it fills up and rebuilds start failing to install their kernel, which is
  # exactly how /boot reached 96% before.
  boot.loader.systemd-boot.configurationLimit = 10;

  # ------------------------------------------------------------- identity ----
  # hostName is set per-host in hosts/<name>/default.nix

  time.timeZone = "America/New_York";
  i18n.defaultLocale = "en_US.UTF-8";

  # ---------------------------------------------------------------- nix -----

  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Keep the store from creeping back to 217 GB.
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 30d";
  };
  nix.optimise.automatic = true;

  # Retained from the previous config. Nothing unfree is currently pulled in now
  # that the DisplayLink driver is gone, but leaving it on avoids a surprise
  # eval failure later.
  nixpkgs.config.allowUnfree = true;

  # -------------------------------------------------------------- network ----

  # NetworkManager is heavier than a server needs, but it is what currently holds
  # the DHCP lease on enp2s0. Swapping to systemd-networkd is a change worth making
  # from the console, not over the SSH session it would interrupt.
  networking.networkmanager.enable = true;

  networking.firewall = {
    enable = true;
    # Was [ 2375 22 80 443 ] plus the range 4000-5550 and UDP 24800.
    #   2375      -- unauthenticated, unencrypted Docker daemon API. Nothing was
    #                bound to it, but the hole was declared. Removed.
    #   80/443    -- no web server on this host.
    #   4000-5550 -- 1551 ports for long-dead dev servers.
    #   24800/udp -- Synergy. The desktop is gone.
    # k8s ports get added when the distro is chosen.
    allowedTCPPorts = [ 22 ];
  };


  # --------------------------------------------------------------- access ----

  services.openssh = {
    enable = true;
    settings = {
      PermitRootLogin = "no";
      # NOTE: PasswordAuthentication is deliberately left at its default (true).
      # Key auth works today, so turning it off is good hygiene -- but do it from
      # the console, not remotely, so a mistake is recoverable.
    };
  };

  security.sudo.wheelNeedsPassword = false;

  users.users.geoff = {
    isNormalUser = true;
    description = "geoff";
    extraGroups = [ "networkmanager" "wheel" "docker" ];
    shell = pkgs.zsh;
  };

  # users.users.geoff.shell points here -- dropping this block breaks login.
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestions.enable = true;
    syntaxHighlighting.enable = true;
    ohMyZsh = {
      enable = true;
      theme = "lambda";
      plugins = [ "git" ];
    };
  };

  # -------------------------------------------------------------- packages ----

  environment.systemPackages = with pkgs; [
    # basics
    wget curl git rsync tree jq gnumake fzf vifm-full
    # diagnostics -- nvme-cli and smartmontools were both missing when the SSD
    # health check was needed, which meant shelling out to nix-shell to read it.
    htop tmux nvme-cli smartmontools pciutils usbutils bind
    # nix tooling
    nixpkgs-fmt
  ];

  # ------------------------------------------------------------- container ----

  # Left enabled: the box still has containers on it and Docker is not in k3s's
  # way. Revisit when the k8s distro lands -- k3s ships its own containerd, so
  # this may become redundant.
  virtualisation.docker.enable = true;

  # ------------------------------------------------------------------ state ----

  # Frozen at the original install value on purpose. This is not a "current
  # version" field and must not be bumped to match the release.
  system.stateVersion = "23.05";
}
