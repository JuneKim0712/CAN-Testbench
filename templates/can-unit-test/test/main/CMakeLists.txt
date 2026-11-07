idf_component_register(SRCS "test_main.c" "../../main/message_handler.c"
                       INCLUDE_DIRS "." "../../main"
                       REQUIRES unity can_driver)
