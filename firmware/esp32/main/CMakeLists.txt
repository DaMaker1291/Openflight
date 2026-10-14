idf_component_register(SRCS "bench_main.cpp" "gen/model.cpp"
                    INCLUDE_DIRS "." "gen"
                    REQUIRES driver esp_timer)
