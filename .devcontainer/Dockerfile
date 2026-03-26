FROM docker.io/trophime/magnettools:trixie

# This Dockerfile adds a non-root user with sudo access. Use the "remoteUser"
# property in devcontainer.json to use it. On Linux, the container user's GID/UIDs
# will be updated to match your local UID/GID (when using the dockerFile property).
# See https://aka.ms/vscode-remote/containers/non-root-user for details.
# $(docker inspect docker.io/trophime/magnettools:trixie --format '{{.Config.User}}')
ARG USERNAME=jovyan
ARG USER_UID=1000
ARG USER_GID=$USER_UID


COPY motd /etc/motd

USER root
RUN echo '[ ! -z "$TERM" ] && cat /etc/motd' >> /etc/bash.bashrc

USER jovyan
