import platform
import shutil
import sys
from pathlib import Path


def main():
    root_dir = Path.cwd()
    build_dir = root_dir / "build"
    dist_dir = root_dir / "dist"
    bin_dir = dist_dir / "bin"
    inc_dir = dist_dir / "include"

    system_os = platform.system()
    if system_os == "Windows":
        zip_name = "rafx_release_win_amd64"
        lib_ext = ".dll"
        implib_ext = ".lib"
    elif system_os == "Linux":
        zip_name = "rafx_release_linux_amd64"
        lib_ext = ".so"
        implib_ext = None
    else:
        print(f"Unsupported OS: {system_os}")
        sys.exit(1)

    # clean previous dist
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    bin_dir.mkdir(parents=True, exist_ok=True)
    inc_dir.mkdir(parents=True, exist_ok=True)

    print(f"Packaging artifacts for {system_os}...")

    files_to_copy = [
        (root_dir / "include/rafx.h", inc_dir),
        (root_dir / "LICENSE", dist_dir),
    ]

    # platform specific files
    if system_os == "Windows":
        files_to_copy.append((build_dir / f"rafx{lib_ext}", bin_dir))
        files_to_copy.append((build_dir / f"rafx{implib_ext}", bin_dir))

        files_to_copy.append((build_dir / "_deps/slang-src/bin/slang.dll", bin_dir))
        files_to_copy.append(
            (build_dir / "_deps/slang-src/bin/slang-compiler.dll", bin_dir)
        )
        files_to_copy.append(
            (build_dir / "_deps/dxc-src/bin/x64/dxcompiler.dll", bin_dir)
        )
        files_to_copy.append((build_dir / "_deps/dxc-src/bin/x64/dxil.dll", bin_dir))

    elif system_os == "Linux":
        files_to_copy.append((build_dir / f"librafx{lib_ext}", bin_dir))

        files_to_copy.append((build_dir / "_deps/slang-src/lib/libslang.so", bin_dir))
        files_to_copy.append(
            (build_dir / "_deps/slang-src/lib/libslang-compiler.so", bin_dir)
        )

    for src, dst in files_to_copy:
        try:
            if src.exists():
                shutil.copy(src, dst)
                print(f"Copied: {src.name}")
            else:
                print(f"Skipped (not found): {src}")
        except Exception as e:
            print(f"Error copying {src}: {e}")

    print(f"Zipping to {zip_name}.zip...")
    shutil.make_archive(zip_name, "zip", dist_dir)
    print("Done.")


if __name__ == "__main__":
    main()
