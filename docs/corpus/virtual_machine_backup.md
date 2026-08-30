---
id: virtual_machine_backup
title: Azure Virtual Machine Backup
source: https://learn.microsoft.com/en-us/azure/backup/backup-azure-vms-introduction
version: 2026-08-30
updated: 2026-08-30
---

# Azure Virtual Machine Backup

Azure Backup can protect Azure virtual machines by creating recovery points in a Recovery Services vault.

## Backup process

For an application-consistent recovery point, Azure Backup uses a VM extension to coordinate with the workload. Crash-consistent recovery points do not capture application memory state.

The first backup is a full backup. Later backups normally transfer only changed disk blocks, which reduces storage and network use.

## Restore choices

A recovery point can be used to create a new virtual machine, restore disks, or replace existing disks. Restoring a VM is distinct from merely taking a managed-disk snapshot.

## Operational considerations

Backup policy controls the schedule and retention of recovery points. A workload owner should test restores and select retention according to recovery objectives rather than assuming that a successful backup guarantees recoverability.
