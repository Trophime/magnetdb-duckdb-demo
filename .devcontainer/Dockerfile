FROM docker.io/trophime/magnettools:trixie

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

RUN (getent group $USER_GID > /dev/null 2>&1 || groupadd --gid $USER_GID $USERNAME) \
    && (id -u $USERNAME > /dev/null 2>&1 || useradd -s /bin/bash --uid $USER_UID --gid $USER_GID -m $USERNAME) \
    && (grep -qF "$USERNAME ALL=(ALL) NOPASSWD:ALL" /etc/sudoers || echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers)
    && mkdir -p ~${USERNAME}/.ssh/ \
    && ssh-keyscan github.com >> ~${USERNAME}/.ssh/known_hosts \
    && chown -R ${USERNAME}.$USER_GID ~${USERNAME}/.ssh

RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get -y install texlive-latex-base texlive-latex-extra dvipng cm-super-minimal \
    && apt-get -y install git-lfs \
    && apt-get -y autoremove --purge \
    && apt-get clean

USER myuser
