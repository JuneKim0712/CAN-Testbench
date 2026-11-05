# Fa26-CalSol-FW-Final-Project

1. install esp-idf
2. find the folder ([...]/esp/esp-idf)
3. install.bat esp32
4. Copy the absolute file path
5. In your VS Code terminal, run export script:

C:\esp\v6.1-beta1\esp-idf\export.ps1

5.5. To set esp target to eps32s3

idf.py set-target esp32s3

6. To build:

idf.py build

7. To flash:

idf.py flash OR
idf.py -p [port e.g. COM6] flash

8. If you had to do any configs:

idf.py menuconfig

9. To monitor:
idf.py -p COM6 monitor

Note: you can do all three at once: idf.py build flash monitor

io42 - 1-pin
io3 - multicolor
https://docs.google.com/forms/d/e/1FAIpQLSfY_UEVlylxT7UW9sK-u9gITkq-qQYcIuhCPNOVRxrd5zwnUg/viewform?pli=1&pli=1&edit2=2_ABaOnufS8z0nLragHD33LmQhw1-ypno3lkGFY7MqolGQ_pyBQBqan7MEg3vrjqh5Qw