#!/bin/bash
docker-compose -f docker-compose.yml -f docker-compose.auth.yml up -d --remove-orphans
