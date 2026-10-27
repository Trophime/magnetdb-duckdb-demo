ARG BASE_IMAGE=debian:trixie
# Local image for now, built from Trophime/magnettools docker/Dockerfile-DB;
# only pulled by the with-magnettools target (BuildKit skips unused stages)
ARG MAGNETTOOLS_IMAGE=magnettools-db:trixie-1.2.6
FROM ${MAGNETTOOLS_IMAGE} AS magnettools-db

# Student devcontainer (devcontainer.json): no MagnetTools
FROM ${BASE_IMAGE} AS base

# This Dockerfile adds a non-root user with sudo access. Use the "remoteUser"
# property in devcontainer.json to use it. On Linux, the container user's GID/UIDs
# will be updated to match your local UID/GID (when using the dockerFile property).
# See https://aka.ms/vscode-remote/containers/non-root-user for details.
# $(docker inspect docker.io/trophime/magnettools:trixie --format '{{.Config.User}}')
ARG USERNAME=myuser
ARG USER_UID=1001
ARG USER_GID=$USER_UID

COPY motd /etc/motd

USER root
RUN echo '[ ! -z "$TERM" ] && cat /etc/motd' >> /etc/bash.bashrc

RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get -y install sudo openssh-client \
    && (getent group $USER_GID > /dev/null 2>&1 || groupadd --gid $USER_GID $USERNAME) \
    && (id -u $USERNAME > /dev/null 2>&1 || useradd -s /bin/bash --uid $USER_UID --gid $USER_GID -m $USERNAME) \
    && (grep -qF "$USERNAME ALL=(ALL) NOPASSWD:ALL" /etc/sudoers || echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers) \
    && mkdir -p ~${USERNAME}/.ssh/ \
    && ssh-keyscan github.com >> ~${USERNAME}/.ssh/known_hosts \
    && chown -R ${USERNAME}.$USER_GID ~${USERNAME}/.ssh

# python3: Debian's interpreter for the venvs (VENV_PYTHON=/usr/bin/python3)
RUN apt-get -y install texlive-latex-base texlive-latex-extra dvipng cm-super-minimal \
    && apt-get -y install git-lfs \
    && apt-get -y install --no-install-recommends python3 \
    && apt-get -y autoremove --purge \
    && apt-get clean

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

USER ${USERNAME}

# LNCMI staff devcontainer (local/devcontainer.json): base + MagnetTools
FROM base AS with-magnettools

ARG USERNAME=myuser

USER root
COPY motd-magnettools /etc/motd

# MagnetTools from the magnettools-db image's local apt repository:
# libmagnettools1 for the wheels in /opt/magnettools/wheels (installed by
# setup-uv.sh) and python3-magnettools for the --system-site-packages venv
COPY --from=magnettools-db /opt/magnettools/ /opt/magnettools/
RUN echo "deb [trusted=yes] file:/opt/magnettools/debs ./" > /etc/apt/sources.list.d/magnettools.list \
    && apt-get update \
    && apt-get -y install --no-install-recommends libmagnettools1 python3-magnettools python3-venv \
    && apt-get clean

USER ${USERNAME}
