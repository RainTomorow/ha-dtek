# We match the tag exactly
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

# CRITICAL: Install playwright BUT pin it to match the Docker tag above!
# This prevents it from downloading version 1.58.0 and breaking.
RUN pip install aiohttp playwright==1.49.1

COPY run.py /run.py
CMD [ "python3", "/run.py" ]