{ ... }:

{
  # A mini node runs the complete substrate, including builds. The individual
  # modules still require the host to state its paths, network sources, worker
  # budget, and Flux repository; this role supplies no machine-specific guesses.
  chuggy.mini.enable = true;
}
