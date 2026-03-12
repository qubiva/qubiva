FROM debian:bookworm-slim

# Install dependencies including AWS CLI prerequisites
RUN apt-get update -y && \
    apt-get install -y \
    wget \
    less \
    curl \
    jq \
    git \
    python3 \
    python3-pip \
    coreutils \
    apt-transport-https \
    lsb-release \
    gnupg \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install AWS CLI
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf aws awscliv2.zip

# Install Azure CLI
RUN mkdir -p /etc/apt/keyrings && \
    curl -sLS https://packages.microsoft.com/keys/microsoft.asc | \
    gpg --dearmor | \
    tee /etc/apt/keyrings/microsoft.gpg > /dev/null && \
    chmod go+r /etc/apt/keyrings/microsoft.gpg && \
    AZ_REPO=$(lsb_release -cs) && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ $AZ_REPO main" | \
    tee /etc/apt/sources.list.d/azure-cli.list && \
    apt-get update && \
    apt-get install -y azure-cli && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Google Cloud SDK
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key --keyring /usr/share/keyrings/cloud.google.gpg add - && \
    apt-get update -y && \
    apt-get install -y google-cloud-sdk && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create runner user and set up directories with correct permissions
RUN useradd -m -s /bin/bash runner && \
    mkdir -p /workspace && \
    chown -R runner:runner /workspace

# Switch to runner user
USER runner
WORKDIR /home/runner

# Set environment variables - IMPORTANT: Point to home directory
ENV STEAMPIPE_UPDATE_CHECK=false \
    STEAMPIPE_TELEMETRY=none \
    HOME="/home/runner" \
    STEAMPIPE_INSTALL_DIR="/home/runner" \
    STEAMPIPE_HOME="/home/runner/.steampipe" \
    PATH="/home/runner/bin:$PATH"

# Create necessary directories
RUN mkdir -p /home/runner/output && \
    mkdir -p /home/runner/bin && \
    mkdir -p /home/runner/.steampipe

# Copy runner script
COPY --chown=runner:runner runner.sh /home/runner/runner.sh
RUN chmod +x /home/runner/runner.sh

# Expose query engine ports and add shared memory size
EXPOSE 9193 9194

# Run with increased shared memory
ENTRYPOINT ["/home/runner/runner.sh"]