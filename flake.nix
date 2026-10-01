{
  description = "Extra overlays and nix-darwin modules for brew-nix packages";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    brew-nix = {
      url = "github:BatteredBunny/brew-nix";
      flake = false;
    };

    brew-api-extra = {
      url = "github:futuping/brew-api-extra";
      flake = false;
    };

    brew-api = {
      url = "github:BatteredBunny/brew-api";
      flake = false;
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      brew-nix,
      brew-api-extra,
      brew-api,
    }:
    let
      requiredBrewApiExtraCaskTokens = import ./overlays/brew-api-extra-cask-tokens.nix;
      lockedBrewApiExtraCasks = builtins.fromJSON (
        builtins.readFile "${brew-api-extra.outPath}/cask.json"
      );
      lockedBrewApiExtraCaskTokens = builtins.map (cask: cask.token) lockedBrewApiExtraCasks;
      missingBrewApiExtraCaskTokens = builtins.filter (
        token: !(builtins.elem token lockedBrewApiExtraCaskTokens)
      ) requiredBrewApiExtraCaskTokens;
      brewApiExtraLockIsConsistent =
        if missingBrewApiExtraCaskTokens == [ ] then
          true
        else
          builtins.throw ''
            brew-api-extra lock is missing required cask token(s): ${builtins.concatStringsSep ", " missingBrewApiExtraCaskTokens}
            Run: nix flake update brew-api-extra
          '';
      googleChromeOverlay = import ./overlays/google-chrome.nix;
      motrixNextOverlay = import ./overlays/motrix-next.nix {
        inherit brew-api-extra brew-nix;
      };
      neteasemusicOverlay = import ./overlays/neteasemusic.nix;
      thirdPartyCasksOverlay = import ./overlays/third-party-casks.nix {
        inherit brew-api-extra brew-nix;
      };
      uuremoteOverlay = import ./overlays/uuremote.nix;
      forAllSystems = nixpkgs.lib.genAttrs [
        "aarch64-darwin"
        "x86_64-linux"
      ];
      maintainerFor =
        system:
        import ./nix/maintainer.nix {
          inherit self;
          pkgs = import nixpkgs { inherit system; };
        };
    in
    assert brewApiExtraLockIsConsistent;
    {
      checks = forAllSystems (
        system:
        import ./tests/catalog-packages.nix {
          inherit nixpkgs system;
          module = self.darwinModules.third-party-casks;
          catalog = lockedBrewApiExtraCasks;
          tokens = requiredBrewApiExtraCaskTokens;
        }
        // import ./tests/uuremote.nix {
          inherit
            nixpkgs
            system
            brew-nix
            brew-api
            ;
          module = self.darwinModules.uuremote;
        }
      );

      devShells = forAllSystems (system: {
        maintainer = (maintainerFor system).devShell;
      });

      apps =
        forAllSystems (system: {
          maintainer-check = (maintainerFor system).checkApp;
        })
        // {
          aarch64-darwin = {
            maintainer-check = (maintainerFor "aarch64-darwin").checkApp;
            update-google-chrome = (maintainerFor "aarch64-darwin").updateApp;
          };
        };

      overlays = {
        google-chrome = googleChromeOverlay;
        motrix-next = motrixNextOverlay;
        neteasemusic = neteasemusicOverlay;
        third-party-casks = thirdPartyCasksOverlay;
        uuremote = uuremoteOverlay;
        default = self.overlays.motrix-next;
      };

      darwinModules = {
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
        uuremote = import ./modules/uuremote.nix {
          overlay = uuremoteOverlay;
        };
        wetype = import ./modules/wetype.nix;
        default = self.darwinModules.wetype;
      };
    };
}
