{
  nixpkgs,
  system,
  module,
  catalog,
  tokens,
}:

let
  inherit (nixpkgs) lib;
  pkgs = import nixpkgs { inherit system; };
  moduleConfig = lib.evalModules {
    modules = [
      {
        options.nixpkgs.overlays = lib.mkOption {
          type = lib.types.listOf lib.types.raw;
          default = [ ];
        };
      }
      module
    ];
  };
  probe =
    variation:
    let
      packages = import nixpkgs {
        system = "aarch64-darwin";
        overlays = [
          (_: _: { brewCasks.existing-cask = "preserved"; })
        ]
        ++ moduleConfig.config.nixpkgs.overlays;
      };
      checkToken =
        token:
        let
          cask = lib.findFirst (entry: entry.token == token) (throw "missing ${token}") catalog;
          package = packages.brewCasks.${token}.override { inherit variation; };
          source = if variation == null then cask else cask.variations.${variation};
          app = (builtins.head cask.artifacts).app;
        in
        assert package.version == cask.version;
        assert package.src.url == source.url;
        assert package.src.outputHash == source.sha256;
        assert package.sourceRoot == builtins.head app;
        package.drvPath;
    in
    assert packages.brewCasks.existing-cask == "preserved";
    map checkToken tokens;
  derivations = lib.concatMap probe [
    null
    "tahoe"
  ];
in
{
  # Force the real module, overlay and both asset variants during --no-build
  # evaluation. Nixpkgs 26.11 no longer supports x86_64-darwin, so the Intel
  # variation is checked under the supported Apple Silicon package set.
  catalog-packages = builtins.deepSeq derivations (
    pkgs.runCommand "catalog-packages-evaluated" { } ''
      touch "$out"
    ''
  );
}
