@echo off
if not exist "build/" (
    mkdir build
    cd build
    cmake .. -G"Visual Studio 18 2026" -DCMAKE_BUILD_TYPE=Debug -DRAFX_BUILD_EXAMPLES=ON -DRAFX_D3D12_SUPPORT=ON
    cd ..
)

cmake --build build --config Debug
if %errorlevel% neq 0 (
    exit /b %errorlevel%
)
