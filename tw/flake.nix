{
  description = "tw - SQLite-backed issue tracker for AI agents";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;

        tw = python.pkgs.buildPythonApplication {
          pname = "tw";
          version = "0.1.0";
          pyproject = true;

          src = ./.;

          build-system = [ python.pkgs.setuptools ];

          dependencies = with python.pkgs; [
            click
            rich
            pydantic
            jinja2
            questionary
            watchdog
            textual
          ];

          meta = {
            description = "SQLite-backed issue tracker for AI agents";
            homepage = "https://github.com/williballenthin/aiwilli/tree/main/tw";
            mainProgram = "tw";
          };
        };
      in
      {
        packages = {
          default = tw;
          tw = tw;
        };

        apps.default = {
          type = "app";
          program = "${tw}/bin/tw";
        };
      }
    );
}
