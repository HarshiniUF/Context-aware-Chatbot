# WSP Contextual Agricultural Chatbot
#
# Build:  docker build -t wsp-chatbot .
# Run:    docker run -it --rm --env-file .env \
#           -v "$PWD/soil:/data/soil:ro" -v "$PWD/eGHR:/data/eGHR:ro" wsp-chatbot
# Other entry points: append the script, e.g. `wsp-chatbot wsp_unified_forecast.py demo`

FROM python:3.12-slim

# libeccodes: needed by cfgrib/eccodes (WSP 3 ECMWF GRIB decoding)
# libexpat1: needed by rasterio's bundled GDAL (eGHR soil fallback, soil_tool.py)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libeccodes0 libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# GHR soil data (soil/, eGHR/) is mounted here at runtime, not baked into the image
ENV GHR_SOIL_DIR=/data \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python"]
CMD ["tool_agent.py"]
