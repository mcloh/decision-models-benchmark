#!/usr/bin/env bash
# Sonda do ambiente padrão dos jobs do Data Science.
set -x
whoami; echo "HOME=$HOME PWD=$PWD"; cat /etc/os-release | head -3; uname -m
which python3 python conda curl tar unzip git 2>&1
python3 --version 2>&1; python3 -c "import oci; print('oci', oci.__version__)" 2>&1
df -h $HOME /tmp 2>&1 | tail -3; nproc; free -g | head -2
nvidia-smi 2>&1 | head -5
env | grep -E '^(JOB_|OCI_|CONDA|DMB_|NB_)' | sed -E 's/(TOKEN|KEY|SECRET)=.*/\1=***/' | sort
ls "$PWD" | head; ls /home/datascience 2>&1 | head
timeout 5 curl -sI https://pypi.org | head -1 || echo "sem internet"
