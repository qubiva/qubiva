FROM alpine:3.18

# Install necessary tools
RUN apk add --no-cache \
    git \
    wget \
    unzip \
    bash \
    curl \
    jq \
    coreutils

# Create runner user and set up directories
RUN adduser -D -s /bin/bash runner && \
    mkdir -p /workspace /usr/local/terraform-versions /usr/local/conftest-versions && \
    chown -R runner:runner /workspace /usr/local/terraform-versions /usr/local/conftest-versions && \
    chown runner:runner /usr/local/bin

# Switch to runner user
USER runner
WORKDIR /workspace

# Copy runner script
COPY --chown=runner:runner runner.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/runner.sh

# Set environment variables
ENV HOME="/home/runner" \
    TERRAFORM_HOME="/home/runner/.terraform"

ENTRYPOINT ["/usr/local/bin/runner.sh"]
