cmake_minimum_required(VERSION 3.20)
project(axis_memlab_disabled LANGUAGES C CXX)

option(AXMEM_DISABLED "Build the explicitly disabled API examples" OFF)
if(NOT AXMEM_DISABLED)
  message(FATAL_ERROR "Only AXMEM_DISABLED=ON is implemented in milestone 0000")
endif()
foreach(mode AXMEM_COUNTERS AXMEM_LEDGER AXMEM_SAMPLER)
  if(DEFINED ${mode})
    if(${mode})
      message(FATAL_ERROR "${mode} is not implemented; only AXMEM_DISABLED=ON is supported")
    endif()
  endif()
endforeach()

add_library(axis_memlab_probe_disabled INTERFACE)
target_include_directories(axis_memlab_probe_disabled INTERFACE include)
target_compile_definitions(axis_memlab_probe_disabled INTERFACE AXMEM_DISABLED=1)

add_executable(axis_memlab_c_example examples/c_api.c)
target_link_libraries(axis_memlab_c_example PRIVATE axis_memlab_probe_disabled)
set_target_properties(axis_memlab_c_example PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES)

add_executable(axis_memlab_cpp_example examples/cpp_raii.cpp)
target_link_libraries(axis_memlab_cpp_example PRIVATE axis_memlab_probe_disabled)
set_target_properties(axis_memlab_cpp_example PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED YES)

enable_testing()
add_subdirectory(tests)
