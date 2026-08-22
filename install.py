import os
import subprocess

def select_target_disk():
    print("\n--- Available Disks ---")

    # Run lsblk to list block devices
    result = subprocess.run(
        ["lsblk", "-dno", "NAME,SIZE,TYPE"],
        capture_output=True,
        text=True
    )

    # Filter only disk-type devices
    lines = result.stdout.strip().split("\n")
    disks = [line for line in lines if "disk" in line]

    disk_list = []

    for idx, line in enumerate(disks, 1):
        name, size, _ = line.split()
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
                print("Invalid number.")

        except ValueError:
            print("Please enter a number.")

    # Safety confirmation prompt
    confirm = input(
        f"WARNING: ALL DATA ON {selected_disk} WILL BE WIPED! "
        "Continue? (y/N): "
    )

    if confirm.lower() != "y":
        print("Installation aborted.")
        exit(1)

    return selected_disk


# Usage
target_disk = select_target_disk()
print(f"Installing onto: {target_disk}")

subprocess.run(
    ["parted", target_disk, "--", "mklabel", "gpt"]
)
subprocess.run(
    ["parted", target_disk, "--", "mkpart", "ext4", "512MB", "-8GB"]
)
print ("Done.")



