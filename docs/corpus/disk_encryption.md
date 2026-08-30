---
id: disk_encryption
title: Azure Virtual Machine Disk Encryption Overview
source: https://learn.microsoft.com/en-us/azure/virtual-machines/disk-encryption-overview
version: 2026-08-30
updated: 2026-08-30
---

# Azure Virtual Machine Disk Encryption Overview

Azure managed disks are encrypted at rest by default with server-side encryption. Encryption at rest protects data persisted on the storage service.

## Platform-managed and customer-managed keys

Server-side encryption can use platform-managed keys or, for supported configurations, customer-managed keys held in Azure Key Vault or Managed HSM. Key choice is separate from the guest operating system's volume encryption.

## Azure Disk Encryption

Azure Disk Encryption uses BitLocker on Windows and DM-Crypt on Linux to encrypt operating-system and data volumes inside the guest. It is a different layer from storage-service server-side encryption.

## Encryption at host

Encryption at host encrypts data on the virtual machine host before it reaches the storage service. Support depends on VM configuration and region capabilities; verify current support before deployment.
