cmake_minimum_required(VERSION 3.20)
project(axis_memlab_native LANGUAGES C CXX)

# Exactly one mode must be chosen explicitly; instrumentation is never enabled by default.
option(AXMEM_DISABLED "Header-only no-op API (no data, no I/O)" OFF)
option(AXMEM_COUNTERS "Relaxed-atomic counters, resource totals, JSONL snapshots" OFF)
option(AXMEM_LEDGER "COUNTERS plus fixed-capacity identity ledger (development use)" OFF)
option(AXMEM_SAMPLER "Allocation sampling (milestone 0004; not implemented)" OFF)

if(AXMEM_SAMPLER)
  message(FATAL_ERROR "AXMEM_SAMPLER is owned by milestone 0004 and is not implemented")
endif()
set(_axmem_selected 0)
foreach(mode AXMEM_DISABLED AXMEM_COUNTERS AXMEM_LEDGER)
  if(${mode})
    math(EXPR _axmem_selected "${_axmem_selected} + 1")
    set(AXMEM_MODE_NAME ${mode})
  endif()
endforeach()
if(NOT _axmem_selected EQUAL 1)
  message(FATAL_ERROR
    "Select exactly one of -DAXMEM_DISABLED=ON, -DAXMEM_COUNTERS=ON, -DAXMEM_LEDGER=ON "
    "(${_axmem_selected} selected)")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED YES)
set(CMAKE_CXX_EXTENSIONS NO)

if(MSVC)
  add_compile_options(/W4 /permissive-)
  add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
else()
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

enable_testing()

if(AXMEM_DISABLED)
  add_library(axis_memlab_probe INTERFACE)
  target_include_directories(axis_memlab_probe INTERFACE include)
  target_compile_definitions(axis_memlab_probe INTERFACE AXMEM_DISABLED=1)

  add_executable(axis_memlab_c_example examples/c_api.c)
  target_link_libraries(axis_memlab_c_example PRIVATE axis_memlab_probe)
  set_target_properties(axis_memlab_c_example PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES)

  add_executable(axis_memlab_cpp_example examples/cpp_raii.cpp)
  target_link_libraries(axis_memlab_cpp_example PRIVATE axis_memlab_probe)
else()
  find_package(Threads REQUIRED)
  add_library(axis_memlab_probe STATIC src/probe.cpp src/self_proc.cpp)
  target_include_directories(axis_memlab_probe PUBLIC include)
  target_compile_definitions(axis_memlab_probe PUBLIC ${AXMEM_MODE_NAME}=1)
  target_link_libraries(axis_memlab_probe PUBLIC Threads::Threads)

  add_executable(axis_memlab_lifecycle_simulator examples/lifecycle_simulator.cpp)
  target_link_libraries(axis_memlab_lifecycle_simulator PRIVATE axis_memlab_probe)

  add_executable(axis_memlab_overhead_bench examples/overhead_bench.cpp)
  target_link_libraries(axis_memlab_overhead_bench PRIVATE axis_memlab_probe)

  add_executable(axis_memlab_queue_metrics_example examples/queue_metrics.cpp)
  target_link_libraries(axis_memlab_queue_metrics_example PRIVATE axis_memlab_probe)

  add_executable(axis_memlab_vdo_lifecycle_example examples/vdo_lifecycle.cpp)
  target_link_libraries(axis_memlab_vdo_lifecycle_example PRIVATE axis_memlab_probe)
endif()

add_subdirectory(tests)
