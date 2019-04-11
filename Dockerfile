#flywheel/csv-import

# Start with python 3.7
FROM python:3.7 as base
MAINTAINER Flywheel <support@flywheel.io>

# Install pandas
COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Flywheel spec (v0)
WORKDIR /flywheel/v0

# Copy executables into place
COPY run.py ./run.py

# Add a default command
CMD ["python run.py"]

# Make a target for testing locally
FROM base as testing
COPY tests ./tests
RUN pip install -r tests/requirements.txt

