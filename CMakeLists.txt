cmake_minimum_required(VERSION 3.20)
project(axis_memlab_native LANGUAGES C CXX)

# Tests are registered in native/tests; enabling testing here lets `ctest --test-dir <build>`
# find them from the top-level build directory.
enable_testing()

add_subdirectory(native)
