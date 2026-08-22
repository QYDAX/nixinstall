import os
import sys
import subprocess


def select_target_disk():
    print("\n--- Available Disks ---")

    # Run lsblk to list block devices
    result = subprocess.run(
        ["lsblk", "-dno", "NAME,SIZE,TYPE"],
        capture_output=True,
        text=True,
        check=True,
    )

    # Strip whitespace and filter out zram, loop, and non-disk types
    lines = [
        line.strip() for line in result.stdout.splitlines() if line.strip()
    ]
    disks = [
        line
        for line in lines
        if "disk" in line and "zram" not in line and "loop" not in line
    ]

    if not disks:
        print("Error: No suitable target disks found!")
        sys.exit(1)

    disk_list = []

    for idx, line in enumerate(disks, 1):
        parts = line.split()
        name = parts[0]
        size = parts[1]
        full_path = f"/dev/{name}"
        disk_list.append(full_path)
        print(f"[{idx}] {full_path} ({size})")

    # Get disk selection
    while True:
        try:
            choice = (
                int(
                    input(
                        "\nSelect the disk to install NixOS onto (e.g. 1): "
                    )
                )
                - 1
            )

            if 0 <= choice < len(disk_list):
                selected_disk = disk_list[choice]
                break
            else:
                print("Invalid selection.")

        except ValueError:
            print("Please enter a number.")

    # Safety confirmation prompt
    confirm = input(
        f"WARNING: ALL DATA ON {selected_disk} WILL BE WIPED! Continue? (y/N): "
    )

    if confirm.lower() != "y":
        print("Installation aborted.")
        sys.exit(0)

    return selected_disk


def main():
    # ----------------------------------------------------------------------
    # Step 1: Disk Selection
    # ----------------------------------------------------------------------
    target_disk = select_target_disk()
    print(f"\nInstalling onto: {target_disk}")

    # Handle partition Naming schemes (/dev/vda1 vs /dev/nvme0n1p1)
    part_prefix = (
        "p" if "nvme" in target_disk or "mmcblk" in target_disk else ""
    )
    boot_part = f"{target_disk}{part_prefix}1"
    root_part = f"{target_disk}{part_prefix}2"
    swap_part = f"{target_disk}{part_prefix}3"

    # ----------------------------------------------------------------------
    # Step 2: Partitioning (GPT / UEFI)
    # ----------------------------------------------------------------------
    print("\n[1/6] Partitioning disk with parted...")

    # Create GPT partition table
    subprocess.run(
        ["parted", target_disk, "--", "mklabel", "gpt"], check=True
    )

    # Boot partition (512MB)
    subprocess.run(
        [
            "parted",
            target_disk,
            "--",
            "mkpart",
            "ESP",
            "fat32",
            "1MB",
            "512MB",
        ],
        check=True,
    )

    # Root partition (Remaining space except final 8GB)
    subprocess.run(
        ["parted", target_disk, "--", "mkpart", "root", "ext4", "512MB", "-8GB"],
        check=True,
    )

    # Swap partition (Final 8GB)
    subprocess.run(
        [
            "parted",
            target_disk,
            "--",
            "mkpart",
            "swap",
            "linux-swap",
            "-8GB",
            "100%",
        ],
        check=True,
    )

    # Set ESP flag on boot partition
    subprocess.run(
        ["parted", target_disk, "--", "set", "1", "esp", "on"], check=True
    )

    # ----------------------------------------------------------------------
    # Step 3: Formatting
    # ----------------------------------------------------------------------
    print("\n[2/6] Formatting partitions...")

    # Format Root (ext4)
    subprocess.run(["mkfs.ext4", "-F", "-L", "nixos", root_part], check=True)

    # Format Swap
    subprocess.run(["mkswap", "-L", "swap", swap_part], check=True)

    # Format Boot (fat32)
    subprocess.run(
        ["mkfs.fat", "-F", "32", "-n", "boot", boot_part], check=True
    )

    # ----------------------------------------------------------------------
    # Step 4: Mounting Filesystems
    # ----------------------------------------------------------------------
    print("\n[3/6] Mounting target filesystems...")

    # Mount Root to /mnt
    subprocess.run(["mount", "/dev/disk/by-label/nixos", "/mnt"], check=True)

    # Mount Boot to /mnt/boot
    os.makedirs("/mnt/boot", exist_ok=True)
    subprocess.run(
        ["mount", "-o", "umask=077", "/dev/disk/by-label/boot", "/mnt/boot"],
        check=True,
    )

    # Enable Swap
    subprocess.run(["swapon", swap_part], check=True)

    # ----------------------------------------------------------------------
    # Step 5: Generating Hardware Configuration & Writing configuration.nix
    # ----------------------------------------------------------------------
    print("\n[4/6] Generating NixOS hardware configuration...")
    subprocess.run(["nixos-generate-config", "--root", "/mnt"], check=True)

    print("\n[5/6] Writing configuration.nix...")
    nixos_config = """{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
  ];

  # Bootloader Configuration (Required for UEFI)
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  # Network & System
  networking.hostName = "nixos";
  networking.networkmanager.enable = true;

  time.timeZone = "UTC";

  # Do not change this value after initial installation
  system.stateVersion = "24.05";
}
"""

    with open("/mnt/etc/nixos/configuration.nix", "w") as f:
        f.write(nixos_config)

    # ----------------------------------------------------------------------
    # Step 6: Installing NixOS
    # ----------------------------------------------------------------------
    print("\n[6/6] Running nixos-install...")
    subprocess.run(["nixos-install"], check=True)

    print("\nInstallation Complete! You can now reboot the system.")


if __name__ == "__main__":
    main()


