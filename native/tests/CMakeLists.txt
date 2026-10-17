if(AXMEM_DISABLED)
  add_test(NAME disabled_c_api_smoke COMMAND axis_memlab_c_example)
  add_test(NAME disabled_cpp_raii_smoke COMMAND axis_memlab_cpp_example)
else()
  # Each scenario is its own executable because the registry is process-global.
  function(axmem_test name source)
    add_executable(${name} ${source})
    target_link_libraries(${name} PRIVATE axis_memlab_probe)
    add_test(NAME ${name} COMMAND ${name})
  endfunction()

  add_executable(test_self_proc test_self_proc.cpp ../src/self_proc.cpp)
  target_include_directories(test_self_proc PRIVATE ../src)
  add_test(NAME test_self_proc COMMAND test_self_proc)

  axmem_test(test_registry test_registry.cpp)
  axmem_test(test_snapshot test_snapshot.cpp)
  axmem_test(test_output_cap test_output_cap.cpp)
  add_test(NAME benchmark_smoke COMMAND axis_memlab_overhead_bench 20000)
  add_test(NAME example_queue_metrics COMMAND axis_memlab_queue_metrics_example
           ${CMAKE_CURRENT_BINARY_DIR}/queue_metrics_example.jsonl)
  add_test(NAME example_vdo_lifecycle COMMAND axis_memlab_vdo_lifecycle_example
           ${CMAKE_CURRENT_BINARY_DIR}/vdo_lifecycle_example.jsonl)

  if(AXMEM_COUNTERS)
    axmem_test(test_resources_counters test_resources_counters.cpp)
  endif()
  if(AXMEM_LEDGER)
    axmem_test(test_ledger test_ledger.cpp)
    axmem_test(test_ledger_concurrent test_ledger_concurrent.cpp)

    # Tiny capacity so overflow and probe wrap-around are exercised.
    add_library(axis_memlab_probe_tiny STATIC ../src/probe.cpp ../src/self_proc.cpp)
    target_include_directories(axis_memlab_probe_tiny PUBLIC ../include)
    target_compile_definitions(axis_memlab_probe_tiny PUBLIC AXMEM_LEDGER=1 AXMEM_LEDGER_CAPACITY=8)
    target_link_libraries(axis_memlab_probe_tiny PUBLIC Threads::Threads)
    add_executable(test_ledger_overflow test_ledger_overflow.cpp)
    target_link_libraries(test_ledger_overflow PRIVATE axis_memlab_probe_tiny)
    add_test(NAME test_ledger_overflow COMMAND test_ledger_overflow)
  endif()
endif()

# Combining modes, or asking for the unimplemented sampler, must fail at configure time.
add_test(
  NAME reject_two_modes
  COMMAND ${CMAKE_COMMAND}
    -S ${PROJECT_SOURCE_DIR}
    -B ${CMAKE_CURRENT_BINARY_DIR}/reject-two-modes
    -DAXMEM_DISABLED=ON
    -DAXMEM_COUNTERS=ON
)
set_tests_properties(reject_two_modes PROPERTIES WILL_FAIL TRUE)
add_test(
  NAME reject_unimplemented_sampler
  COMMAND ${CMAKE_COMMAND}
    -S ${PROJECT_SOURCE_DIR}
    -B ${CMAKE_CURRENT_BINARY_DIR}/reject-sampler
    -DAXMEM_DISABLED=ON
    -DAXMEM_SAMPLER=ON
)
set_tests_properties(reject_unimplemented_sampler PROPERTIES WILL_FAIL TRUE)
add_test(
  NAME reject_no_mode
  COMMAND ${CMAKE_COMMAND}
    -S ${PROJECT_SOURCE_DIR}
    -B ${CMAKE_CURRENT_BINARY_DIR}/reject-no-mode
)
set_tests_properties(reject_no_mode PROPERTIES WILL_FAIL TRUE)
