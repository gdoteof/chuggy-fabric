# The repositories this site carries, and the one place they are declared.
#
# A repository is named across many places -- the credential lists, the
# scheduler's maps, the mirror job, the importer, and the GitHub App tokens on
# the host -- and every one of them reads correctly while another is missing
# the entry. So the site declares each repository once here, and its readers
# derive from it: `hosts/gtr/default.nix` mints that repository's tokens,
# `tests/github-repository-transition.py` refuses a rendered cluster in which
# any repository below is absent from any of those places, and `flake.nix`
# builds the check that refuses a roster whose apps are missing.
#
# ADDING A REPOSITORY IS ADDING AN ENTRY HERE, AND THEN DOING WHAT THE GATE
# SAYS. `cluster/apps` is plain YAML that kustomize applies with no templating
# -- the trade cluster/apps/kustomization.yaml records -- so nothing generates
# those manifests from this file. The gate is what closes the gap: it names the
# manifest, the variable and the value each missing entry needs, so the list
# below is the roster and the gate is the checklist it produces.
#
# THE KEY IS THE REPOSITORY'S NAME ON BOTH FORGES. It is the name of the GitHub
# repository under `owner`, and the name of the bare repository the rig's git
# service serves; the gate holds both URLs to it. That is what lets one entry
# name a repository everywhere without repeating the name.
#
# THE INSTALLATION IDS ARE PER OWNER AND PER APP. A GitHub App installation is
# an owner's, so a repository under a second owner is a second installation of
# each App even though the Apps are the same two. They are readable from that
# account's app settings page and nowhere else.
#
# AN OWNER MUST ALSO CARRY THE RULESET THAT MAKES ITS WORKER TOKEN SAFE. The
# worker token an entry mints is `contents: write` and reaches every
# agent-executed pod that can reach github.com, so the owner's default branch
# needs a ruleset admitting only the portal App integration and repository
# admins to update it -- the way `Finalizer owns main` does on
# gdoteof/chuggy-fabric and `chuggy portal + admins own main` does on
# kasofsk/chuggy -- and this file cannot check that a second owner has one.

let
  # The bare repositories the rig's git service serves, and the only place its
  # address is written in this file.
  gitService = "http://git.chuggy-git.svc.cluster.local.";

  site = {
    chuggy = {
      owner = "kasofsk";
      portalInstallationId = "156333284";
      workerInstallationId = "156786211";
      imported = true;
    };

    # The fabric is under its own GitHub owner and in the same tenant and
    # project as chuggy.
    #
    # IT IS ALSO THE FLUX SOURCE: `hosts/gtr/default.nix`'s
    # `chuggy.flux.repositoryUrl` names this same repository, so a finalized
    # fabric ticket is a change Flux applies to this cluster once it merges.
    #
    # `imported = false` IS THE ONE THING THIS SITE CANNOT YET DO, and it is
    # not a manifest that was forgotten. The configuration importer takes one
    # commit for every partition it is given and resolves each partition's
    # repository from its binding, so a project bound to two repositories has
    # no commit that means both. kasofsk/chuggy's own step -- the importer
    # taking a repository with the commit -- is what makes this `true`, and
    # that is the whole of the follow-up: this line, and the entry
    # cluster/apps/chuggy-configuration-importer.yaml's list then accepts.
    chuggy-fabric = {
      owner = "gdoteof";
      portalInstallationId = "156334058";
      workerInstallationId = "156791042";
      imported = false;
    };
  };
in
builtins.mapAttrs
  (name: entry: {
    inherit (entry) owner imported;

    # What every consumer of a repository addresses it by: the forge, and the
    # in-cluster mirror the sync job keeps equal to it.
    github = "https://github.com/${entry.owner}/${name}.git";
    mirror = "${gitService}/${name}.git";

    # The file a control-plane pod reads this repository's GitHub token from,
    # under whichever credential root that pod mounts, and the credential slot
    # a worker pod resolves it under. Both are per repository because the token
    # is: a second owner is a second installation and therefore a second Secret.
    credentialFile = "${name}-github";
    workerCredential = "${name}-github-worker";

    # Exactly the shape `chuggy.githubAppTokens.repositories` takes, so a host
    # passes it through rather than restating it. The role each Secret serves
    # is modules/github-app-token.nix's; the names are here because the
    # manifests that mount them are held against these.
    tokens = {
      repository = name;
      inherit (entry) portalInstallationId workerInstallationId;
      readerSecret = "${name}-github-reader-token";
      finalizerSecret = "${name}-github-finalizer-token";
      buildReaderSecret = "${name}-build-source-read";
      workerSecret = "${name}-github-worker-token";
    };
  })
  site
