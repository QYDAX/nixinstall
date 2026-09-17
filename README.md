# nixinstall
A command line nixos installer, similar to archinstall. 
To use nixinstall, log in under su and run the following command.
It is not production ready yet; Not all DE's have been tested, just KDE and Caelestia Shell. All tests have been done bare metal on a core i7 6th gen system.
Legacy Boot (MBR) is not supported; UEFI must be used, unstable branch is recommended.
```bash
nix-shell -p python3 curl --run "install_script=$(mktemp) && curl -sSL [raw.githubusercontent.com/qydax/nixinstall/main/install.py](https://raw.githubusercontent.com/qydax/nixinstall/main/install.py) -o \"$install_script\" && python3 \"$install_script\" && rm -f \"$install_script\""
