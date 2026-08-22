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
        check=True
    )
    
    # Strip whitespace and filter out zram, loop, and non-disk types
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    disks = [line for line in lines if "disk" in line and "zram" not in line and "loop" not in line]

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
            choice = int(
                input("\nSelect the disk to install NixOS onto (e.g. 1): ")
            ) - 1

            if 0 <= choice < len(disk_list):
                selected_disk = disk_list[choice]
                break
            else:
                print("Invalid selection.")

        except ValueError:
            print("Please enter a number.")

    # Safety confirmation prompt
    confirm = input(
        f"WARNING: ALL DATA ON {selected_disk} WILL BE WIPED! "
        "Continue? (y/N): "
    )

    if confirm.lower() != "y":
        print("Installation aborted.")
        sys.exit(0)

    return selected_disk


# ----------------------------------------------------------------------
# Step 1: Disk Selection
# ----------------------------------------------------------------------
target_disk = select_target_disk()
print(f"\nInstalling onto: {target_disk}")

# Determine device node names for partitions (handles /dev/nvme0n1p1 vs /dev/sda1)
part_prefix = "p" if "nvme" in target_disk or "mmcblk" in target_disk else ""
boot_part = f"{target_disk}{part_prefix}1"
root_part = f"{target_disk}{part_prefix}2"
swap_part = f"{target_disk}{part_prefix}3"

# ----------------------------------------------------------------------
# Step 2: Partitioning (UEFI / GPT Scheme)
# ----------------------------------------------------------------------
print("\n[1/5] Partitioning disk with parted...")

# Create GPT partition table
subprocess.run(["parted", target_disk, "--", "mklabel", "gpt"], check=True)

# Add ESP Boot partition (512MB)
subprocess.run(["parted", target_disk, "--", "mkpart", "ESP", "fat32", "1MB", "512MB"], check=True)

# Add Root partition (Fill disk except final 8GB)
subprocess.run(["parted", target_disk, "--", "mkpart", "root", "ext4", "512MB", "-8GB"], check=True)

# Add Swap partition (Final 8GB)
subprocess.run(["parted", target_disk, "--", "mkpart", "swap", "linux-swap", "-8GB", "100%"], check=True)

# Set ESP flag on Boot partition
subprocess.run(["parted", target_disk, "--", "set", "1", "esp", "on"], check=True)

# ----------------------------------------------------------------------
# Step 3: Formatting
# ----------------------------------------------------------------------
print("\n[2/5] Formatting partitions...")

# Format Root partition with ext4 and label 'nixos'
subprocess.run(["mkfs.ext4", "-F", "-L", "nixos", root_part], check=True)

# Initialize Swap partition with label 'swap'
subprocess.run(["mkswap", "-L", "swap", swap_part], check=True)

# Format Boot partition with FAT32 and label 'boot'
subprocess.run(["mkfs.fat", "-F", "32", "-n", "boot", boot_part], check=True)

# ----------------------------------------------------------------------
# Step 4: Mounting Filesystems
# ----------------------------------------------------------------------
print("\n[3/5] Mounting target filesystems...")

# Mount root to /mnt
subprocess.run(["mount", "/dev/disk/by-label/nixos", "/mnt"], check=True)

# Create /mnt/boot and mount EFI boot partition
os.makedirs("/mnt/boot", exist_ok=True)
subprocess.run(["mount", "-o", "umask=077", "/dev/disk/by-label/boot", "/mnt/boot"], check=True)

# Activate Swap
subprocess.run(["swapon", swap_part], check=True)

# ----------------------------------------------------------------------
# Step 5: Generating Initial NixOS Configuration
# ----------------------------------------------------------------------
print("\n[4/5] Generating NixOS hardware configuration...")
subprocess.run(["nixos-generate-config", "--root", "/mnt"], check=True)
# ----------------------------------------------------------------------
# Step 5b: Inject Bootloader Configuration
# ----------------------------------------------------------------------
print("\nConfiguring systemd-boot for UEFI...")

bootloader_config = """
  # Enable systemd-boot UEFI bootloader
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
"""

config_path = "/mnt/etc/nixos/configuration.nix"

# Append bootloader config right before the closing brace of configuration.nix
with open(config_path, "r") as f:
    content = f.read()

# Replace the closing brace with the bootloader options and re-close the attribute set
if "boot.loader.systemd-boot.enable" not in content:
    content = content.rstrip()
    if content.endswith("}"):
        content = content[:-1] + bootloader_config + "\n}\n"
    with open(config_path, "w") as f:
        f.write(content)

# ----------------------------------------------------------------------
# Step 6: Performing the Installation
# ----------------------------------------------------------------------
print("\n[5/5] Running nixos-install...")
subprocess.run(["nixos-install"], check=True)

print("\nInstallation Complete! You can now type 'reboot'.")



