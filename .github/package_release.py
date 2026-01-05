import os
import platform
import shutil
import sys
from pathlib import Path


def copy_slang_binaries(src_dir, dst_dir, system_os):
    targets = []

    if system_os == "Windows":
        targets = ["slang.dll", "slang-compiler.dll"]
        extra_targets = ["slang.lib", "slang-compiler.lib"]
        for t in extra_targets:
            if (src_dir / t).exists():
                targets.append(t)
    elif system_os == "Linux":
        targets = ["libslang.so", "libslang-compiler.so"]
    elif system_os == "Darwin":
        targets = ["libslang.dylib", "libslang-compiler.dylib"]

    print(f"Copying Slang binaries from {src_dir}...")

    for filename in targets:
        src = src_dir / filename
        dst = dst_dir / filename

        if src.exists():
            try:
                shutil.copy(src, dst)
                print(f"  Copied: {filename}")
            except Exception as e:
                print(f"  Failed to copy {filename}: {e}")
        else:
            print(f"  {filename} not found in {src_dir}")


def main():
    root_dir = Path.cwd()
    build_dir = root_dir / "build"
    dist_dir = root_dir / "dist"
    bin_dir = dist_dir / "bin"
    inc_dir = dist_dir / "include"

    system_os = platform.system()

    target_arch = os.environ.get("RAFX_TARGET_ARCH", platform.machine()).lower()

    if system_os == "Windows":
        if "arm64" in target_arch or "aarch64" in target_arch:
            zip_name = "rafx_release_win_arm64"
        else:
            zip_name = "rafx_release_win_amd64"
            target_arch = "x64"

        lib_ext = ".dll"
        implib_ext = ".lib"
    elif system_os == "Linux":
        if "aarch64" in target_arch or "arm64" in target_arch:
            zip_name = "rafx_release_linux_arm64"
        else:
            zip_name = "rafx_release_linux_amd64"

        lib_ext = ".so"
        implib_ext = None
    elif system_os == "Darwin":
        if "arm" in target_arch or "aarch" in target_arch:
            arch_name = "arm64"
        else:
            arch_name = "x64"

        zip_name = f"rafx_release_macos_{arch_name}"
        lib_ext = ".dylib"
        implib_ext = None
    else:
        print(f"Unsupported OS: {system_os}")
        sys.exit(1)

    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    bin_dir.mkdir(parents=True, exist_ok=True)
    inc_dir.mkdir(parents=True, exist_ok=True)

    print(f"Packaging artifacts for {system_os} ({target_arch})...")

    files_to_copy = [
        (root_dir / "include/rafx.h", inc_dir),
        (root_dir / "LICENSE", dist_dir),
    ]

    if system_os == "Windows":
        files_to_copy.append((build_dir / f"rafx{lib_ext}", bin_dir))
        files_to_copy.append((build_dir / f"rafx{implib_ext}", bin_dir))
    elif system_os == "Linux":
        files_to_copy.append((build_dir / f"librafx{lib_ext}", bin_dir))
    elif system_os == "Darwin":
        files_to_copy.append((build_dir / f"librafx{lib_ext}", bin_dir))

    for src, dst in files_to_copy:
        try:
            if src.exists():
                shutil.copy(src, dst)
                print(f"Copied: {src.name}")
            else:
                print(f"Skipped (not found): {src}")
        except Exception as e:
            print(f"Error copying {src}: {e}")

    slang_base = build_dir / "_deps/slang-src"

    if system_os == "Windows":
        copy_slang_binaries(slang_base / "bin", bin_dir, system_os)

        dxc_arch = "arm64" if "arm64" in target_arch else "x64"
        dxc_bin = build_dir / f"_deps/dxc-src/bin/{dxc_arch}"

        if dxc_bin.exists():
            print(f"Copying DXC binaries from {dxc_bin}...")
            for f in ["dxcompiler.dll", "dxil.dll"]:
                src = dxc_bin / f
                if src.exists():
                    shutil.copy(src, bin_dir)
                    print(f"  Copied: {f}")
        else:
            print(f"DXC binaries not found at {dxc_bin} (Skipping)")

    elif system_os == "Linux":
        copy_slang_binaries(slang_base / "lib", bin_dir, system_os)
    elif system_os == "Darwin":
        copy_slang_binaries(slang_base / "lib", bin_dir, system_os)

    print(f"Zipping to {zip_name}.zip...")
    shutil.make_archive(zip_name, "zip", dist_dir)
    print("Done.")


if __name__ == "__main__":
    main()
