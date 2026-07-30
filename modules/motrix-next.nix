{ overlay }:

{ lib, ... }:

{
  nixpkgs.overlays = lib.mkAfter [ overlay ];
}
