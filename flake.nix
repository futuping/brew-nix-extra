{
  description = "Extra nix-darwin modules for brew-nix packages";

  inputs = {
    brew-nix = {
      url = "github:BatteredBunny/brew-nix";
      flake = false;
    };

    brew-api-extra = {
      url = "github:futuping/brew-api-extra";
      flake = false;
    };
  };

  outputs =
    {
      self,
      brew-nix,
      brew-api-extra,
    }:
    {
      darwinModules = {
        motrix-next = import ./modules/motrix-next.nix {
          inherit brew-api-extra brew-nix;
        };
        wetype = import ./modules/wetype.nix;
        default = self.darwinModules.wetype;
      };
    };
}
