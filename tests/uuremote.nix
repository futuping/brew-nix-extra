{
  nixpkgs,
  system,
  brew-nix,
  brew-api,
  module,
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
  baseOverlay = final: _: {
    brewCasks = import "${brew-nix}/casks.nix" {
      pkgs = final;
      inherit brew-api;
    };
  };
  base = import nixpkgs {
    system = "aarch64-darwin";
    overlays = [ baseOverlay ];
  };
  patched = import nixpkgs {
    system = "aarch64-darwin";
    overlays = [ baseOverlay ] ++ moduleConfig.config.nixpkgs.overlays;
  };
  original = base.brewCasks.uuremote;
  package = patched.brewCasks.uuremote;
  verified =
    assert package.version == original.version;
    assert package.src.name == original.src.name;
    assert package.src.outputHash == original.src.outputHash;
    assert package.src.outputHashAlgo == "sha256";
    assert package.src.outputHash != "";
    assert
      package.src.urls == original.src.urls
      ++ [
        "https://api.nrd.nie.163.com/api/v1/release/dl/4?channel=gwqd"
      ];
    assert package.unpackPhase == original.unpackPhase;
    assert package.installPhase == original.installPhase;
    assert patched.brewCasks.wechat.drvPath == base.brewCasks.wechat.drvPath;
    [
      package.src.drvPath
      package.drvPath
    ];
in
{
  # Force the real official cask, module and overlay during no-build checks.
  uuremote = builtins.deepSeq verified (
    pkgs.runCommand "uuremote-evaluated" { } ''
      touch "$out"
    ''
  );
}
