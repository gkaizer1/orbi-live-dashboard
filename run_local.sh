#!/bin/bash

export ROUTER_ADMIN_PASSWORD="<INPUT_PASSWORD_HERE>"

export FLASK_ENV=development
export FLASK_DEBUG=1

python3.7 main.py -p 8091