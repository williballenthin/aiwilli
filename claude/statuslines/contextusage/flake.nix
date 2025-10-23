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

        claude-contextusage-statusline = pkgs.rustPlatform.buildRustPackage {
          pname = "claude-contextusage-statusline";
          version = "0.1.0";

          src = ./.;

          cargoLock = {
            lockFile = ./Cargo.lock;
          };

          meta = with pkgs.lib; {
            description = "Claude context usage statusline";
            homepage = "https://github.com/aiwilli/claude";
            license = licenses.mit;
            maintainers = [ ];
            mainProgram = "claude-contextusage-statusline";
          };
        };
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
            cargo
            rustc
            rust-analyzer
            rustfmt
            clippy
          ];
        };
      }
    );
}
