cmake_minimum_required(VERSION 3.20)
project(axis_memlab_native LANGUAGES C CXX)

# Only support POSIX (UNIX-like) platforms. Fail loudly on non-POSIX (e.g., Windows).
if (NOT UNIX)
  message(FATAL_ERROR "This project only supports POSIX systems (UNIX). Windows or non-POSIX builds are not supported.")
endif()

# Tests are registered in native/tests; enabling testing here lets `ctest --test-dir <build>`
# find them from the top-level build directory.
enable_testing()

add_subdirectory(native)
