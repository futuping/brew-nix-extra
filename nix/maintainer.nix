{ self, pkgs }:

let
  python = pkgs.python313.withPackages (p: [ p.pyyaml ]);
  isolation = ''
    export PYTHONNOUSERSITE=1
    export PYTHONDONTWRITEBYTECODE=1
  '';
  check = pkgs.writeShellApplication {
    name = "maintainer-check";
    text = ''
      ${isolation}
      cd "${self}"
      ${pkgs.findutils}/bin/find . -name '*.nix' \
        -exec ${pkgs.nixfmt}/bin/nixfmt --check {} +
      ${python}/bin/python3 -m unittest discover -s tests
      ${python}/bin/python3 -c 'from pathlib import Path; import yaml; [yaml.safe_load(p.read_text()) for p in Path(".github/workflows").glob("*.yml")]'
      ${pkgs.nix}/bin/nix flake check --all-systems --no-build --no-update-lock-file "${self}"
    '';
  };
  update = pkgs.writeShellApplication {
    name = "update-google-chrome";
    text = ''
      ${isolation}
      case "$PWD" in
        /nix/store/*) echo "Run from a writable brew-nix-extra checkout." >&2; exit 1 ;;
      esac
      if [[ ! -f flake.nix || ! -f scripts/update_google_chrome.py || ! -f sources/google-chrome.json ]]; then
        echo "Run from the brew-nix-extra repository root." >&2
        exit 1
      fi
      exec ${python}/bin/python3 "$PWD/scripts/update_google_chrome.py" \
        "$@" --source "$PWD/sources/google-chrome.json"
    '';
  };
in
{
  devShell = pkgs.mkShellNoCC {
    packages = [
      pkgs.nix
      pkgs.nixfmt
      pkgs.git
      python
    ];
    PYTHONNOUSERSITE = "1";
    PYTHONDONTWRITEBYTECODE = "1";
  };
  checkApp = {
    type = "app";
    program = "${check}/bin/maintainer-check";
  };
  updateApp = {
    type = "app";
    program = "${update}/bin/update-google-chrome";
  };
}
