{
  description = "Extra nix-darwin modules for brew-nix packages";

  outputs =
    { self }:
    {
      darwinModules = {
        wetype = import ./modules/wetype.nix;
        default = self.darwinModules.wetype;
      };
    };
}
