{
  brew-api-extra,
  brew-nix,
}:

{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.motrix-next;

  thirdPartyBrewCasks = import "${brew-nix}/casks.nix" {
    inherit pkgs;
    brew-api = brew-api-extra.outPath;
  };

  # The upstream app is not Developer ID signed. Normalize its linker-generated
  # ad-hoc signature into a valid signature for the complete application bundle.
  motrixNextPackage = thirdPartyBrewCasks."motrix-next".overrideAttrs (oldAttrs: {
    installPhase = oldAttrs.installPhase + ''
      /usr/bin/codesign --force --deep --sign - \
      "$out/Applications/MotrixNext.app"
    '';
  });
in
{
  options.programs.motrix-next = {
    enable = lib.mkEnableOption "the Motrix Next download manager";

    package = lib.mkOption {
      type = lib.types.package;
      default = motrixNextPackage;
      description = "Motrix Next application bundle to install.";
    };
  };

  config.environment.systemPackages = lib.optional cfg.enable cfg.package;
}
