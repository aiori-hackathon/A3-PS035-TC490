# NEXORA Lab — Makefile
# Team: A3-PS035-TC490 | PS-035
#
# All targets operate ONLY on NEXORA-owned containers (project=nexora).
# Never use system-wide Docker cleanup.

LAB_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
COMPOSE_FILE := $(LAB_DIR)docker-compose.yml
PROJECT := nexora
LAB_SH := $(LAB_DIR)lab.sh

.PHONY: lab-up lab-down lab-status lab-verify lab-logs lab-restart lab-failover lab-restore-sysctl help

help:
	@echo "NEXORA Lab Commands:"
	@echo "  make lab-up             Start the five-router OSPF ring lab"
	@echo "  make lab-down           Stop and remove NEXORA lab containers"
	@echo "  make lab-status         Show container and OSPF neighbor status"
	@echo "  make lab-verify         Run all connectivity and OSPF checks"
	@echo "  make lab-logs           Show all container logs"
	@echo "  make lab-restart        Teardown and restart"
	@echo "  make lab-failover       Run L12 link-failure smoke test"
	@echo "  make lab-restore-sysctl Restore recorded host sysctl setting"

lab-up:
	@bash $(LAB_SH) up

lab-down:
	@bash $(LAB_SH) down

lab-status:
	@bash $(LAB_SH) status

lab-verify:
	@bash $(LAB_SH) verify

lab-logs:
	@bash $(LAB_SH) logs

lab-restart:
	@bash $(LAB_SH) restart

lab-failover:
	@bash $(LAB_SH) failover

lab-restore-sysctl:
	@bash $(LAB_SH) restore-sysctl
