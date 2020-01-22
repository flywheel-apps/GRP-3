FROM python:3.7-slim-stretch
MAINTAINER Flywheel <support@flywheel.io>

ENV FLYWHEEL="/flywheel/v0"
COPY ["requirements.txt", "/opt/requirements.txt"]
RUN pip install -r /opt/requirements.txt \
    && mkdir -p $FLYWHEEL \
    && useradd --no-user-group --create-home --shell /bin/bash flywheel

COPY utils $FLYWHEEL/utils
COPY run.py manifest.json $FLYWHEEL/
RUN chmod +x $FLYWHEEL/run.py

WORKDIR $FLYWHEEL

