idf_component_register(SRCS "test_main.c" "../../main/pedal_logic.c"
                       INCLUDE_DIRS "." "../../main"
                       REQUIRES unity can_driver)
