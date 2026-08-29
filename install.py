#!/usr/bin/env python3

import getpass
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path


NIXOS_STATE_VERSION = "25.11"
MIN_DISK_GB = 16

LB_REPO = "https://github.com/LinuxBeginnings/NixOS-Hyprland.git"
CAELESTIA_SHELL_REPO = "github:caelestia-dots/shell"


def run_command(command, **kwargs):
    """Run a command and stop the installer if it fails."""
    print(f"\n--> {' '.join(command)}")
    return subprocess.run(command, check=True, **kwargs)


def command_exists(command):
    return shutil.which(command) is not None


def check_required_commands():
    """Make sure the installer environment has everything it needs."""

    required = [
        "lsblk",
        "parted",
        "mkfs.ext4",
        "mkfs.fat",
        "mount",
        "nixos-generate-config",
        "nixos-install",
        "git",
        "cp",
        "findmnt",
        "partprobe",
        "udevadm",
        "openssl",
    ]

    missing = [cmd for cmd in required if not command_exists(cmd)]

    if missing:
        print("[ERROR] Missing required commands:")
        for cmd in missing:
            print(f"  - {cmd}")

        print("\nMake sure you are running this from the NixOS installer.")
        sys.exit(1)


def check_uefi():
    """Require the installer to have been booted in UEFI mode."""

    if not os.path.exists("/sys/firmware/efi"):
        print("[ERROR] This installer was not booted in UEFI mode.")
        print("Please reboot the installer USB in UEFI mode.")
        sys.exit(1)


def check_network():
    """Check basic network connectivity."""

    print("\n--> Checking network connectivity...")

    try:
        subprocess.run(
            ["ping", "-c", "1", "-W", "3", "github.com"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[ERROR] Network connectivity check failed.")
        print("An Internet connection is required for this installer.")
        sys.exit(1)


def get_nix_system():
    """Detect system architecture and map it to a Nix system string."""

    arch = platform.machine().lower()

    if arch in ["x86_64", "amd64"]:
        return "x86_64-linux"

    if arch in ["aarch64", "arm64"]:
        return "aarch64-linux"

    print(f"[ERROR] Unsupported architecture: {arch}")
    sys.exit(1)


def get_hostname():
    """Get and sanitize the hostname."""

    detected = socket.gethostname() or "nixos"

    hostname = input(
        f"\nHostname [{detected}]: "
    ).strip()

    if not hostname:
        hostname = detected

    hostname = hostname.lower()

    # Valid Linux hostname characters.
    if not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
        hostname,
    ):
        print("[ERROR] Invalid hostname.")
        print("Use only lowercase letters, numbers, and hyphens.")
        sys.exit(1)

    return hostname


def get_username():
    """Ask for and validate the primary user's username."""

    while True:
        username = input("\nPreferred username: ").strip()

        if not username:
            print("Username cannot be empty.")
            continue

        if len(username) > 32:
            print("Username is too long.")
            continue

        if not re.fullmatch(r"[a-z_][a-z0-9_-]*[$]?", username):
            print(
                "Invalid username. Use lowercase letters, numbers, "
                "underscores, and hyphens."
            )
            continue

        if username in {
            "root",
            "nobody",
            "daemon",
            "bin",
            "sys",
            "sync",
            "games",
            "man",
            "lp",
            "mail",
            "news",
            "uucp",
            "proxy",
            "www-data",
            "backup",
            "list",
            "irc",
            "gnats",
            "systemd-network",
            "systemd-resolve",
        }:
            print("That username is reserved.")
            continue

        return username


def get_password():
    """Prompt for the user's password without echoing it."""

    while True:
        password = getpass.getpass("\nPassword for the new user: ")

        if not password:
            print("Password cannot be empty.")
            continue

        confirmation = getpass.getpass("Retype password: ")

        if password != confirmation:
            print("Passwords do not match.")
            continue

        return password


def hash_password(password):
    """
    Generate a SHA-512 password hash using openssl.

    The plaintext password is never written to configuration.nix.
    """

    try:
        result = subprocess.run(
            ["openssl", "passwd", "-6", "-stdin"],
            input=password,
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        print("[ERROR] openssl is required to hash the password.")
        sys.exit(1)

    return result.stdout.strip()


def disk_size_bytes(device):
    """Return the disk size in bytes."""

    result = subprocess.run(
        ["lsblk", "-bndo", "SIZE", device],
        capture_output=True,
        text=True,
        check=True,
    )

    return int(result.stdout.strip())


def select_target_disk():
    """Display physical disks and ask the user to select one."""

    print("\n--- Available Disks ---")

    result = subprocess.run(
        [
            "lsblk",
            "-dno",
            "NAME,SIZE,TYPE,MODEL",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    disks = []

    for line in lines:
        parts = line.split()

        if len(parts) < 3:
            continue

        name = parts[0]
        size = parts[1]
        disk_type = parts[2]
        model = " ".join(parts[3:]) if len(parts) > 3 else ""

        if disk_type == "disk":
            disks.append(
                {
                    "name": name,
                    "size": size,
                    "model": model,
                }
            )

    if not disks:
        print("[ERROR] No usable disks found.")
        sys.exit(1)

    for index, disk in enumerate(disks, 1):
        model = f" - {disk['model']}" if disk["model"] else ""

        print(
            f"[{index}] /dev/{disk['name']} "
            f"({disk['size']}){model}"
        )

    while True:
        try:
            choice = int(
                input(
                    "\nSelect the disk for NixOS installation: "
                )
            ) - 1

            if 0 <= choice < len(disks):
                break

            print("Invalid selection.")

        except ValueError:
            print("Please enter a number.")

    selected = f"/dev/{disks[choice]['name']}"

    size_gb = disk_size_bytes(selected) / (1024 ** 3)

    print(
        f"\nSelected disk: {selected}"
        f"\nDisk size: {size_gb:.1f} GiB"
    )

    if size_gb < MIN_DISK_GB:
        print(
            f"[ERROR] This installer requires at least "
            f"{MIN_DISK_GB} GiB."
        )
        sys.exit(1)

    confirm = input(
        f"\nWARNING: ALL DATA ON {selected} WILL BE WIPED!\n"
        f"Type 'YES' to continue: "
    ).strip()

    if confirm != "YES":
        print("Installation aborted.")
        sys.exit(0)

    return selected


def check_mounts():
    """Make sure /mnt isn't already being used."""

    result = subprocess.run(
        ["findmnt", "/mnt"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    if result.returncode == 0:
        print("[ERROR] /mnt is already mounted.")
        print("Unmount it before running this installer.")
        sys.exit(1)


def partition_disk(target_disk):
    """Create GPT + ESP + root partitions (No physical swap partition)."""

    print("\n[1/6] Partitioning disk...")

    run_command(
        [
            "parted",
            "--script",
            target_disk,
            "mklabel",
            "gpt",
        ]
    )

    # 1 GiB EFI partition.
    run_command(
        [
            "parted",
            "--script",
            target_disk,
            "mkpart",
            "ESP",
            "fat32",
            "1MiB",
            "1GiB",
        ]
    )

    # Everything remaining goes directly to root.
    run_command(
        [
            "parted",
            "--script",
            target_disk,
            "mkpart",
            "root",
            "ext4",
            "1GiB",
            "100%",
        ]
    )

    run_command(
        [
            "parted",
            "--script",
            target_disk,
            "set",
            "1",
            "esp",
            "on",
        ]
    )

    # Tell the kernel about the new partition table.
    run_command(["partprobe", target_disk])

    # Give udev time to create partition devices.
    subprocess.run(
        ["udevadm", "settle"],
        check=False,
    )


def get_partition_paths(target_disk):
    """Return boot and root partition paths."""

    if "nvme" in target_disk or "mmcblk" in target_disk:
        prefix = "p"
    else:
        prefix = ""

    boot = f"{target_disk}{prefix}1"
    root = f"{target_disk}{prefix}2"

    return boot, root


def format_partitions(boot_part, root_part):
    """Format the boot and root partitions."""

    print("\n[2/6] Formatting partitions...")

    run_command(
        [
            "mkfs.fat",
            "-F",
            "32",
            "-n",
            "BOOT",
            boot_part,
        ]
    )

    run_command(
        [
            "mkfs.ext4",
            "-F",
            "-L",
            "nixos",
            root_part,
        ]
    )


def mount_filesystems(boot_part, root_part):
    """Mount root and boot partitions."""

    print("\n[3/6] Mounting filesystems...")

    os.makedirs("/mnt", exist_ok=True)

    run_command(
        [
            "mount",
            root_part,
            "/mnt",
        ]
    )

    os.makedirs("/mnt/boot", exist_ok=True)

    run_command(
        [
            "mount",
            boot_part,
            "/mnt/boot",
        ]
    )


def generate_hardware_config():
    """Generate NixOS hardware configuration."""

    print("\n[4/6] Generating hardware configuration...")

    run_command(
        [
            "nixos-generate-config",
            "--root",
            "/mnt",
        ]
    )


def create_desktop_configuration(
    desktop,
    nix_system,
    hostname,
    username,
):
    """
    Return:
        desktop_snippet,
        flake_content or None,
        is_flake_build
    """

    desktop_snippet = ""
    flake_content = None
    is_flake_build = False

    if desktop == "1":
        desktop_snippet = """
  services.displayManager.gdm.enable = true;
  services.desktopManager.gnome.enable = true;
"""

    elif desktop == "2":
        desktop_snippet = """
  services.desktopManager.plasma6.enable = true;

  services.displayManager.sddm = {
    enable = true;
    wayland.enable = true;
  };
"""

    elif desktop == "3":
        desktop_snippet = """
  programs.hyprland.enable = true;
  programs.hyprland.xwayland.enable = true;

  environment.systemPackages = with pkgs; [
    kitty
  ];
"""

    elif desktop == "4":
        if nix_system != "x86_64-linux":
            print(
                "\n[WARNING] Caelestia support in this installer "
                f"is only enabled for x86_64-linux."
            )
            print("Falling back to standard Hyprland.")

            desktop_snippet = """
  programs.hyprland.enable = true;
  programs.hyprland.xwayland.enable = true;

  environment.systemPackages = with pkgs; [
    kitty
    waybar
    rofi-wayland
    swaync
  ];
"""

        else:
            is_flake_build = True

            flake_content = f"""{{

  description = "NixOS with Hyprland and Caelestia";

  inputs = {{

    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

    caelestia-shell = {{
      url = "{CAELESTIA_SHELL_REPO}";
      inputs.nixpkgs.follows = "nixpkgs";
    }};

  }};

  outputs = {{ self, nixpkgs, caelestia-shell, ... }}: {{

    nixosConfigurations.{hostname} =
      nixpkgs.lib.nixosSystem {{

        system = "{nix_system}";

        modules = [

          ./hardware-configuration.nix

          ./configuration.nix

          {{
            nix.settings.experimental-features = [
              "nix-command"
              "flakes"
            ];

            programs.hyprland = {{
              enable = true;
              xwayland.enable = true;
            }};

            environment.systemPackages = [
              caelestia-shell.packages.{nix_system}.with-cli
            ];
          }}

        ];

      }};

  }};

}}
"""

            desktop_snippet = """
  # Hyprland and Caelestia are configured by flake.nix.
"""

    elif desktop == "5":
        desktop_snippet = """
  programs.hyprland.enable = true;
  programs.hyprland.xwayland.enable = true;

  environment.systemPackages = with pkgs; [
    waybar
    swaync
    rofi-wayland
    kitty
  ];
"""

    elif desktop == "6":
        desktop_snippet = """
  programs.hyprland.enable = true;
  programs.hyprland.xwayland.enable = true;

  environment.systemPackages = with pkgs; [
    git
    vim
    curl
    pciutils
    waybar
    rofi-wayland
    kitty
  ];
"""

    return desktop_snippet, flake_content, is_flake_build


def select_desktop(
    nix_system,
    hostname,
    username,
):
    """Ask the user which desktop environment to install."""

    print("\n--- Desktop Environment ---")
    print("1. GNOME")
    print("2. KDE Plasma 6")
    print("3. Hyprland (Stock)")
    print("4. Hyprland + Caelestia Shell")
    print("5. Hyprland + Waybar & Rofi Suite")
    print("6. Hyprland + Linux Beginnings")

    while True:
        choice = input("\nEnter choice (1-6): ").strip()

        if choice in {"1", "2", "3", "4", "5", "6"}:
            break

        print("Invalid choice.")

    return create_desktop_configuration(
        choice,
        nix_system,
        hostname,
        username,
    ), choice


def create_configuration(
    hostname,
    username,
    password_hash,
    desktop_snippet,
):
    """Create the final NixOS configuration with zRAM swap enabled."""

    return f"""{{ config, pkgs, ... }}:

{{
  imports = [
    ./hardware-configuration.nix
  ];

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  # Enable zRAM for compressed memory-based swap space
  zramSwap.enable = true;

  networking.hostName = "{hostname}";
  networking.networkmanager.enable = true;

  time.timeZone = "UTC";

  users.users.{username} = {{
    isNormalUser = true;
    description = "{username}";
    home = "/home/{username}";

    extraGroups = [
      "wheel"
      "networkmanager"
    ];

    hashedPassword = "{password_hash}";
  }};

  # Allow the user to use sudo.
  security.sudo.wheelNeedsPassword = true;

{desktop_snippet}

  environment.systemPackages = with pkgs; [
    git
    curl
    wget
    vim
  ];

  system.stateVersion = "{NIXOS_STATE_VERSION}";
}}
"""


def install_linux_beginnings(username):
    """
    Clone the current Linux Beginnings NixOS repository into the
    user's home directory.
    """

    print("\n--> Preparing Linux Beginnings configuration...")

    target_dir = Path(
        f"/mnt/home/{username}/NixOS-Hyprland"
    )

    if target_dir.exists():
        shutil.rmtree(target_dir)

    run_command(
        [
            "git",
            "clone",
            "--depth",
            "1",
            LB_REPO,
            str(target_dir),
        ]
    )

    # Fix ownership.
    run_command(
        [
            "chown",
            "-R",
            f"{username}:{username}",
            str(target_dir),
        ]
    )

    print(
        "\nLinux Beginnings has been cloned to:"
        f"\n  /home/{username}/NixOS-Hyprland"
    )

    print(
        "\nThe current Linux Beginnings repository does not ship "
        "the desktop dotfiles directly in the repository, so this "
        "installer does not pretend that copying .config will install them."
    )


def write_configuration(
    hostname,
    username,
    password_hash,
    desktop_snippet,
):
    """Write configuration.nix."""

    config = create_configuration(
        hostname,
        username,
        password_hash,
        desktop_snippet,
    )

    config_path = Path("/mnt/etc/nixos/configuration.nix")

    print(
        f"\n--> Writing {config_path}..."
    )

    config_path.write_text(config)


def write_flake(flake_content):
    """Write flake.nix if required."""

    if flake_content is None:
        return

    flake_path = Path("/mnt/etc/nixos/flake.nix")

    print(
        f"\n--> Writing {flake_path}..."
    )

    flake_path.write_text(flake_content)


def verify_configuration(is_flake_build, hostname):
    """Run a NixOS configuration check before installation."""

    print("\n--> Checking NixOS configuration...")

    if is_flake_build:
        run_command(
            [
                "nix",
                "flake",
                "check",
                "/mnt/etc/nixos",
            ]
        )

        run_command(
            [
                "nix",
                "eval",
                f"/mnt/etc/nixos#{hostname}.config.system.build.toplevel",
                "--raw",
            ]
        )

    else:
        run_command(
            [
                "nixos-rebuild",
                "build",
                "--no-link",
                "--root",
                "/mnt",
            ]
        )


def install_nixos(is_flake_build, hostname):
    """Perform the actual NixOS installation."""

    print("\n[6/6] Installing NixOS...")

    if is_flake_build:
        command = [
            "nixos-install",
            "--flake",
            f"/mnt/etc/nixos#{hostname}",
            "--no-root-passwd",
        ]
    else:
        command = [
            "nixos-install",
            "--no-root-passwd",
        ]

    run_command(command)


def cleanup():
    """Unmount everything from /mnt."""

    print("\n--> Cleaning up mounts...")

    subprocess.run(
        ["umount", "-R", "/mnt"],
        check=False,
    )


def main():
    # ------------------------------------------------------------
    # Basic checks
    # ------------------------------------------------------------

    if os.geteuid() != 0:
        print("[ERROR] This script must be run as root.")
        print("Run it from the NixOS installer with sudo.")
        sys.exit(1)

    check_required_commands()
    check_uefi()
    check_mounts()
    check_network()

    # ------------------------------------------------------------
    # System information
    # ------------------------------------------------------------

    nix_system = get_nix_system()
    hostname = get_hostname()
    username = get_username()
    password = get_password()
    password_hash = hash_password(password)

    # Remove plaintext password from memory as soon as possible.
    password = None

    print("\n==========================================")
    print("       NixOS Automated System Installer")
    print("==========================================")
    print(f"Architecture : {nix_system}")
    print(f"Hostname     : {hostname}")
    print(f"Username     : {username}")
    print(f"State        : {NIXOS_STATE_VERSION}")

    # ------------------------------------------------------------
    # Disk
    # ------------------------------------------------------------

    target_disk = select_target_disk()

    print(
        f"\nInstalling NixOS onto: {target_disk}"
    )

    # ------------------------------------------------------------
    # Partitioning
    # ------------------------------------------------------------

    partition_disk(target_disk)

    boot_part, root_part = get_partition_paths(
        target_disk
    )

    # ------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------

    format_partitions(
        boot_part,
        root_part,
    )

    # ------------------------------------------------------------
    # Mounting
    # ------------------------------------------------------------

    mount_filesystems(
        boot_part,
        root_part,
    )

    try:
        # --------------------------------------------------------
        # Hardware configuration
        # --------------------------------------------------------

        generate_hardware_config()

        # --------------------------------------------------------
        # Desktop selection
        # --------------------------------------------------------

        (
            desktop_result,
            desktop_choice,
        ) = select_desktop(
            nix_system,
            hostname,
            username,
        )

        (
            desktop_snippet,
            flake_content,
            is_flake_build,
        ) = desktop_result

        # --------------------------------------------------------
        # Write configuration
        # --------------------------------------------------------

        write_configuration(
            hostname,
            username,
            password_hash,
            desktop_snippet,
        )

        write_flake(flake_content)

        # --------------------------------------------------------
        # Linux Beginnings
        # --------------------------------------------------------

        if desktop_choice == "6":
            install_linux_beginnings(username)

        # --------------------------------------------------------
        # Validate configuration
        # --------------------------------------------------------

        verify_configuration(
            is_flake_build,
            hostname,
        )

        # --------------------------------------------------------
        # Install
        # --------------------------------------------------------

        install_nixos(
            is_flake_build,
            hostname,
        )

        print("\n==========================================")
        print("       NixOS Installation Complete")
        print("==========================================")
        print(f"Username : {username}")
        print(f"Hostname : {hostname}")
        print("\nYou can now reboot into your new NixOS system.")

    except subprocess.CalledProcessError as error:
        print(
            "\n[ERROR] A command failed."
        )
        print(
            f"Command: {error.cmd}"
        )
        print(
            f"Exit code: {error.returncode}"
        )
        print(
            "\nThe installation was stopped."
        )
        print(
            "The target partitions have NOT been restored."
        )
        sys.exit(1)

    finally:
        cleanup()


if __name__ == "__main__":
    main()


