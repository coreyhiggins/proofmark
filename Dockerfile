# proofmark, for a VPS, a dedi, or anywhere you would rather not install Python.
#
#   docker build -t proofmark .
#   docker run --rm -p 8765:8765 proofmark
#
# Then open http://localhost:8765 on the machine, or tunnel to it. The server
# binds to 0.0.0.0 inside the container only because Docker's port mapping
# needs it to; publish the port to 127.0.0.1 on the host and it stays local:
#
#   docker run --rm -p 127.0.0.1:8765:8765 proofmark
#
# Do not expose this to the internet without putting authentication in front
# of it. It has none, on purpose, because it is meant to be a local tool.

FROM python:3.12-slim AS build

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.12-slim

# Runs as a non-root user. A container that reads your trading results should
# not also be running as root.
RUN useradd --create-home --uid 10001 proofmark

COPY --from=build /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl[crypto] && rm /tmp/*.whl

USER proofmark
WORKDIR /home/proofmark

EXPOSE 8765

# --no-browser because there is no browser in here to open.
CMD ["proofmark", "gui", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
