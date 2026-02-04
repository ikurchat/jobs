#!/bin/bash
# Virtual framebuffer для headless display

exec Xvfb :99 -screen 0 ${RESOLUTION:-1920x1080x24} -ac +extension GLX +render -noreset
