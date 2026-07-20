FROM debian:trixie

ARG USERNAME=myuser
ARG USER_UID=1000
ARG USER_GID=$USER_UID

COPY motd /etc/motd

USER root

RUN apt-get update \
    && apt-get install -y \
        sudo \
        git \
        git-lfs \
        python3 \
        python3-venv \
        python3-pip \
    && groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} -m -s /bin/bash ${USERNAME}

RUN mkdir -p /mnt/LNCMIG-Data/records \
    && chown -R ${USERNAME}:${USERNAME} /mnt/LNCMIG-Data

USER ${USERNAME}