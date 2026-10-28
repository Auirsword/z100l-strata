FROM ubuntu:24.04 AS build
ARG BUILD_JOBS=4
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build python3 ca-certificates \
    libnuma-dev libelf-dev libdrm-dev libcurl4-openssl-dev libgfortran-13-dev \
    && rm -rf /var/lib/apt/lists/*
COPY .work/src/Strata /opt/strata/src
COPY .work/src/llama.cpp /opt/llama.cpp
# Vendor toolchains are read-only named build contexts, never image layers.
RUN --mount=type=bind,from=dtk,target=/opt/dtk,readonly \
    --mount=type=bind,from=hyhal,target=/opt/hyhal,readonly \
    bash -c 'source /opt/dtk/env.sh && \
    cmake -S /opt/strata/src -B /opt/strata/build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DSTRATA_HIP_GFX906=ON -DCMAKE_HIP_ARCHITECTURES=gfx906 \
      -DSTRATA_BUILD_TESTS=ON -DSTRATA_NATIVE_EXPERTS=ON \
      -DSTRATA_GGML_DIR=/opt/llama.cpp \
      -DCMAKE_C_COMPILER=/opt/dtk/llvm/bin/clang \
      -DCMAKE_CXX_COMPILER=/opt/dtk/llvm/bin/clang++ \
      -DCMAKE_HIP_COMPILER=/opt/dtk/llvm/bin/clang++ && \
    cmake --build /opt/strata/build --target strata strata-device -j "$BUILD_JOBS"'

FROM ubuntu:24.04 AS runtime
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip ca-certificates \
    libnuma1 libelf1 libdrm2 libatomic1 libgfortran5 libcurl4 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/strata/src /opt/strata/src
COPY --from=build /opt/strata/build/strata /opt/strata/bin/strata
COPY --from=build /opt/strata/build/strata-device /opt/strata/bin/strata-device
COPY docker/entrypoint.sh /opt/strata/bin/entrypoint.sh
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r /opt/strata/src/requirements.txt && \
    chmod 0755 /opt/strata/bin/entrypoint.sh && mkdir -p /state/logs /state/conversations
ENV PATH="/opt/venv/bin:/opt/strata/bin:$PATH" \
    PYTHONPATH="/opt/strata/src" \
    ROCM_PATH=/opt/dtk HIP_PATH=/opt/dtk/hip HSA_PATH=/opt/dtk/hsa \
    HOME=/state
WORKDIR /opt/strata/src
EXPOSE 18080
ENTRYPOINT ["/opt/strata/bin/entrypoint.sh"]
CMD ["/opt/venv/bin/python", "-m", "serve.server", "--engine", "strata", "--config", "/state/config/serve.json"]
