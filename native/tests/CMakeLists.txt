add_test(NAME disabled_c_api_smoke COMMAND axis_memlab_c_example)
add_test(NAME disabled_cpp_raii_smoke COMMAND axis_memlab_cpp_example)
add_test(
  NAME reject_unimplemented_counters
  COMMAND ${CMAKE_COMMAND}
    -S ${PROJECT_SOURCE_DIR}
    -B ${CMAKE_CURRENT_BINARY_DIR}/unsupported-counters
    -DAXMEM_DISABLED=ON
    -DAXMEM_COUNTERS=ON
)
set_tests_properties(reject_unimplemented_counters PROPERTIES WILL_FAIL TRUE)
