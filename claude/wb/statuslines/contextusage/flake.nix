{
  description = "Claude context usage statusline";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        claude-contextusage-statusline = pkgs.writeShellScriptBin "claude-contextusage-statusline" ''
          ${pkgs.python3}/bin/python3 ${./statusline.py}
        '';
      in
      {
        packages = {
          default = claude-contextusage-statusline;
          claude-contextusage-statusline = claude-contextusage-statusline;
        };

        apps = {
          default = {
            type = "app";
            program = "${claude-contextusage-statusline}/bin/claude-contextusage-statusline";
          };
          claude-contextusage-statusline = {
            type = "app";
            program = "${claude-contextusage-statusline}/bin/claude-contextusage-statusline";
          };
        };

        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python3
          ];
        };
      }
    );
}