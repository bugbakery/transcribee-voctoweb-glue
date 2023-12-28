let
  pkgs = import
    (builtins.fetchTarball {
      name = "nixos-unstable-stable-23.11";
      url = "https://github.com/nixos/nixpkgs/archive/057f9aecfb71c4437d2b27d3323df7f93c010b7e.tar.gz";
      sha256 = "1ndiv385w1qyb3b18vw13991fzb9wg4cl21wglk89grsfsnra41k";
    })
    { };
in
pkgs.mkShell {
  buildInputs = with pkgs; [
    pre-commit

    python310
    python310Packages.black
    pdm

    # required by pre-commit
    git
    ruff
  ];
}
