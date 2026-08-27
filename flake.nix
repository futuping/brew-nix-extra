{
  description = "Extra overlays and nix-darwin modules for brew-nix packages";

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
    let
      googleChromeOverlay = import ./overlays/google-chrome.nix;
      motrixNextOverlay = import ./overlays/motrix-next.nix {
        inherit brew-api-extra brew-nix;
      };
      neteasemusicOverlay = import ./overlays/neteasemusic.nix;
      thirdPartyCasksOverlay = import ./overlays/third-party-casks.nix {
        inherit brew-api-extra brew-nix;
      };
    in
    {
      overlays = {
        google-chrome = googleChromeOverlay;
        motrix-next = motrixNextOverlay;
        neteasemusic = neteasemusicOverlay;
        third-party-casks = thirdPartyCasksOverlay;
        default = self.overlays.motrix-next;
      };

      darwinModules = {
        awesun = import ./modules/awesun.nix;
        google-chrome = import ./modules/google-chrome.nix {
          overlay = googleChromeOverlay;
        };
        motrix-next = import ./modules/motrix-next.nix {
          overlay = motrixNextOverlay;
        };
        neteasemusic = import ./modules/neteasemusic.nix {
          overlay = neteasemusicOverlay;
        };
        third-party-casks = import ./modules/third-party-casks.nix {
          overlay = thirdPartyCasksOverlay;
        };
        wetype = import ./modules/wetype.nix;
        default = self.darwinModules.wetype;
      };
    };
}
